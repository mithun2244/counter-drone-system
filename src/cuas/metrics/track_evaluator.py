"""Scores the shared tracker against ground truth. Simulator results, not real-world performance.

Each confirmed track belongs to the target it was nearest to most often. Position error is the
distance to that target, on confirmed track messages while the target is still flying. A track
still coasting after its target's flight ended is counted, not scored. Tentative and lost
messages are never scored.
"""

import itertools
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from cuas.schemas import Track
from cuas.sim.truth import TruthLog

FALSE_TRACK_M = (
    50.0  # median distance to every target above this: the track follows nothing
)
P95 = 95
DRONE_TYPES = {"attack_drone", "quadcopter", "friendly_drone"}


@dataclass(frozen=True)
class TrackReport:
    confirmed: int
    false_tracks: int
    tracks_per_target: dict[str, int]
    overlapping_duplicates: int
    """Targets with two confirmed tracks at the same time."""
    sequential_duplicates: int
    """Targets picked up again under a new track ID, never two at once."""
    median_error_m: float | None
    p95_error_m: float | None
    worst_target: tuple[str, float] | None
    scored: int
    after_flight: int
    first_confirmed: dict[str, tuple[float, float]]
    """Per target: time of its first confirmed track, and its distance from the site centre then."""
    drones_tracked: tuple[int, int]
    birds_tracked: tuple[int, int]


def evaluate_tracks(truth: TruthLog, tracks: Sequence[Track]) -> TrackReport:
    positions: defaultdict[float, dict[str, np.ndarray]] = defaultdict(dict)
    types: dict[str, str] = {}
    for state in truth.states:
        positions[state.t][state.target_id] = np.asarray(state.position_enu_m)
        types[state.target_id] = state.target_type
    confirmed = [m for m in tracks if m.status == "confirmed"]
    owner, false = owners(confirmed, positions)
    errors: defaultdict[str, list[float]] = defaultdict(list)
    after_flight = 0
    for message in confirmed:
        target = positions[message.t].get(owner[message.track_id])
        if target is None:
            after_flight += 1
        else:
            errors[owner[message.track_id]].append(_distance(message, target))
    pooled = [e for values in errors.values() for e in values]
    real = sorted(set(owner) - false)
    by_target = {t: [i for i in real if owner[i] == t] for t in sorted(types)}
    overlapping, sequential = _duplicates(by_target, confirmed)
    return TrackReport(
        confirmed=len(owner),
        false_tracks=len(false),
        tracks_per_target={t: len(ids) for t, ids in by_target.items()},
        overlapping_duplicates=overlapping,
        sequential_duplicates=sequential,
        median_error_m=statistics.median(pooled) if pooled else None,
        p95_error_m=float(np.percentile(pooled, P95)) if pooled else None,
        worst_target=max(
            ((t, statistics.median(v)) for t, v in errors.items()),
            key=lambda item: (item[1], item[0]),
            default=None,
        ),
        scored=len(pooled),
        after_flight=after_flight,
        first_confirmed=_first_confirmed(by_target, confirmed, positions),
        drones_tracked=_tracked(by_target, types, DRONE_TYPES),
        birds_tracked=_tracked(by_target, types, {"bird"}),
    )


def _distance(message: Track, target: np.ndarray) -> float:
    return float(np.linalg.norm(np.asarray(message.position_enu_m) - target))


def owners(
    confirmed: list[Track], positions: dict[float, dict[str, np.ndarray]]
) -> tuple[dict[str, str], set[str]]:
    """Each track's target, and the tracks whose median distance to every target is too far."""
    nearest: defaultdict[str, list[tuple[str, float]]] = defaultdict(list)
    for message in confirmed:
        flying = positions.get(message.t, {})
        if flying:
            distances = ((_distance(message, p), t) for t, p in flying.items())
            distance, target = min(distances)
            nearest[message.track_id].append((target, distance))
    owner = {}
    for track_id, seen in nearest.items():
        counts = Counter(target for target, _ in seen)
        owner[track_id] = min(counts, key=lambda t: (-counts[t], t))
    false = {
        track_id
        for track_id, seen in nearest.items()
        if statistics.median(d for _, d in seen) > FALSE_TRACK_M
    }
    return owner, false


def _duplicates(
    by_target: dict[str, list[str]], confirmed: list[Track]
) -> tuple[int, int]:
    spans: dict[str, tuple[float, float]] = {}
    for message in confirmed:
        first, last = spans.get(message.track_id, (message.t, message.t))
        spans[message.track_id] = (min(first, message.t), max(last, message.t))
    overlapping = sequential = 0
    for ids in by_target.values():
        if len(ids) < 2:
            continue
        ordered = sorted(spans[i] for i in ids)
        if any(
            later[0] <= earlier[1] for earlier, later in itertools.pairwise(ordered)
        ):
            overlapping += 1
        else:
            sequential += 1
    return overlapping, sequential


def _first_confirmed(
    by_target: dict[str, list[str]],
    confirmed: list[Track],
    positions: dict[float, dict[str, np.ndarray]],
) -> dict[str, tuple[float, float]]:
    first: dict[str, tuple[float, float]] = {}
    for target, ids in by_target.items():
        times = [m.t for m in confirmed if m.track_id in ids]
        if times:
            t = min(times)
            east, north, _ = positions[t][target]
            first[target] = (t, math.hypot(east, north))
    return first


def _tracked(
    by_target: dict[str, list[str]], types: dict[str, str], wanted: set[str]
) -> tuple[int, int]:
    targets = [t for t in by_target if types[t] in wanted]
    return sum(bool(by_target[t]) for t in targets), len(targets)
