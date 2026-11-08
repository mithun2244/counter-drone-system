"""Scores alerts against ground truth. Simulator results, not real-world performance.

Tracks belong to targets as in the track evaluator. An alert belongs to the target its tracks
belonged to most often, so an alert continued by a re-acquired track still counts once.
"""

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from cuas.metrics.track_evaluator import owners
from cuas.schemas import CoverageStatus, Message, ThreatAssessment, Track
from cuas.sim.truth import TruthLog

RANKS = {"info": 0, "amber": 1, "red": 2}
DRONE_TYPES = {"attack_drone", "quadcopter", "friendly_drone"}
FALSE, UNCONFIRMED = "false track", "unconfirmed track"
FRESH_STATIONS = 2


@dataclass(frozen=True)
class AlertReport:
    alert_owner: dict[str, str]
    """Each alert's target ID, or ``false track`` or ``unconfirmed track``."""
    alerts_per_target: dict[str, int]
    first_red: dict[str, tuple[float, float]]
    """Per target: time of its first red, and seconds since the track carrying it started."""
    wrong_alarms: int
    """Amber or red assessments on anything that is not a drone: birds, false or unconfirmed tracks."""
    wrong_alarm_tracks: dict[str, str]
    red_batches: int
    """Batches with two or more red assessments."""
    out_of_order_batches: int
    """Of those, batches whose ranked order is not the order the targets truly arrive in."""
    stale_rises: int
    """New alerts or level rises on a batch where the track had no fresh fix."""
    coverage: tuple[tuple[float, float, bool], ...]


def evaluate_alerts(truth: TruthLog, messages: Sequence[Message]) -> AlertReport:
    positions: defaultdict[float, dict[str, np.ndarray]] = defaultdict(dict)
    types: dict[str, str] = {}
    arrival: dict[str, float] = {}
    for state in truth.states:
        positions[state.t][state.target_id] = np.asarray(state.position_enu_m)
        types[state.target_id] = state.target_type
        arrival[state.target_id] = state.t
    tracks = [m for m in messages if isinstance(m, Track)]
    threats = [m for m in messages if isinstance(m, ThreatAssessment)]
    owner, false = owners([m for m in tracks if m.status == "confirmed"], positions)

    def belongs(track_id: str) -> str:
        if track_id in false:
            return FALSE
        return owner.get(track_id, UNCONFIRMED)

    def is_drone(track_id: str) -> bool:
        return types.get(belongs(track_id)) in DRONE_TYPES

    wrong = {
        a.track_id: belongs(a.track_id)
        for a in threats
        if a.level != "info" and not is_drone(a.track_id)
    }
    alert_owner = _alert_owners(threats, belongs)
    started = {}
    for m in tracks:
        started.setdefault(m.track_id, m.t)
    first_red: dict[str, tuple[float, float]] = {}
    for a in threats:
        target = belongs(a.track_id)
        if a.level == "red" and is_drone(a.track_id) and target not in first_red:
            first_red[target] = (a.t, a.t - started[a.track_id])
    red_batches, out_of_order = _order(threats, belongs, arrival)
    counted = Counter(alert_owner.values())
    return AlertReport(
        alert_owner=alert_owner,
        alerts_per_target={t: counted.get(t, 0) for t in sorted(types)},
        first_red=first_red,
        wrong_alarms=sum(
            1 for a in threats if a.level != "info" and not is_drone(a.track_id)
        ),
        wrong_alarm_tracks=wrong,
        red_batches=red_batches,
        out_of_order_batches=out_of_order,
        stale_rises=_stale_rises(tracks, threats),
        coverage=tuple(
            (m.t, m.coverage_pct, m.warning)
            for m in messages
            if isinstance(m, CoverageStatus)
        ),
    )


def _alert_owners(threats, belongs) -> dict[str, str]:
    seen: defaultdict[str, Counter] = defaultdict(Counter)
    for a in threats:
        if a.alert_id is not None:
            seen[a.alert_id][belongs(a.track_id)] += 1
    return {
        alert: min(counts, key=lambda target: (-counts[target], target))
        for alert, counts in sorted(seen.items())
    }


def _order(threats, belongs, arrival) -> tuple[int, int]:
    """Batches with 2+ reds, and how many list them out of true arrival order."""
    reds: defaultdict[float, list[ThreatAssessment]] = defaultdict(list)
    for a in threats:
        if a.level == "red":
            reds[a.t].append(a)
    batches = bad = 0
    for listed in reds.values():
        if len(listed) < 2:
            continue
        batches += 1
        targets = [belongs(a.track_id) for a in listed]
        if any(t not in arrival for t in targets) or [
            arrival[t] for t in targets
        ] != sorted(arrival[t] for t in targets):
            bad += 1
    return batches, bad


def _stale_rises(tracks, threats) -> int:
    fresh = {(m.track_id, m.t): m.n_stations >= FRESH_STATIONS for m in tracks}
    previous: dict[str, ThreatAssessment] = {}
    known_alerts: set[str] = set()
    rises = 0
    for a in threats:
        before = previous.get(a.track_id)
        rose = before is not None and RANKS[a.level] > RANKS[before.level]
        new_alert = a.alert_id is not None and a.alert_id not in known_alerts
        if (rose or new_alert) and not fresh.get((a.track_id, a.t), False):
            rises += 1
        if a.alert_id is not None:
            known_alerts.add(a.alert_id)
        previous[a.track_id] = a
    return rises
