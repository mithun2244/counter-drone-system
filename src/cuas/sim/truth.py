"""Ground truth, for the evaluator only. Plain dataclasses, so the bus refuses to carry them."""

from dataclasses import dataclass, field

from cuas.config import TargetType
from cuas.schemas import SensorKind
from cuas.schemas.base import Vector3


@dataclass(frozen=True, slots=True)
class TargetState:
    t: float
    target_id: str
    target_type: TargetType
    position_enu_m: Vector3
    velocity_mps: Vector3


@dataclass(frozen=True, slots=True)
class BearingTruth:
    """What really lay behind one published bearing."""

    t: float
    target_id: str
    target_type: TargetType
    station_id: str
    sensor: SensorKind
    azimuth_deg: float
    elevation_deg: float
    range_m: float
    max_range_m: float


@dataclass(frozen=True, slots=True)
class PicketTruth:
    """What really lay behind one published picket alert. ``t`` is when it was published."""

    t: float
    heard_t: float
    target_id: str
    target_type: TargetType
    picket_id: str
    bearing_deg: float
    distance_m: float
    hearing_radius_m: float
    engine_type: str
    guessed_engine_type: str


@dataclass
class TruthLog:
    states: list[TargetState] = field(default_factory=list)
    bearings: list[BearingTruth] = field(default_factory=list)
    picket_alerts: list[PicketTruth] = field(default_factory=list)
