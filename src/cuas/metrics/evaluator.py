"""The only reader of ground truth. Its numbers are simulator results, not real-world performance."""

from collections import Counter
from dataclasses import dataclass

from cuas.sim.truth import TruthLog


@dataclass(frozen=True)
class TargetSummary:
    """``warning_s`` runs from the first picket alert to the end of the target's flight."""

    target_id: str
    target_type: str
    bearings_by_station: dict[str, int]
    first_bearing_s: float | None
    first_picket_alert_s: float | None
    arrival_s: float
    warning_s: float | None


def summarize(truth: TruthLog) -> list[TargetSummary]:
    """One summary per target, ordered by target ID."""
    last_state = {state.target_id: state for state in truth.states}
    return [
        _summarize_target(
            truth, target_id, last_state[target_id].target_type, last_state[target_id].t
        )
        for target_id in sorted(last_state)
    ]


def _summarize_target(
    truth: TruthLog, target_id: str, target_type: str, arrival_s: float
) -> TargetSummary:
    bearings = [b for b in truth.bearings if b.target_id == target_id]
    alerts = [a for a in truth.picket_alerts if a.target_id == target_id]
    first_alert = min((a.t for a in alerts), default=None)
    return TargetSummary(
        target_id=target_id,
        target_type=target_type,
        bearings_by_station=dict(
            sorted(Counter(b.station_id for b in bearings).items())
        ),
        first_bearing_s=min((b.t for b in bearings), default=None),
        first_picket_alert_s=first_alert,
        arrival_s=arrival_s,
        warning_s=None if first_alert is None else arrival_s - first_alert,
    )
