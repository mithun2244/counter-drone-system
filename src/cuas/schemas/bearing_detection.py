from typing import Annotated, Literal

from pydantic import Field

from cuas.schemas.base import AzimuthDeg, ElevationDeg, Message, Probability, SimTime

SensorKind = Literal["rgb", "thermal", "acoustic", "zoom"]


class BearingDetection(Message):
    """A direction from one station's sensor. Carries no target identity."""

    station_id: str
    sensor: SensorKind
    t: SimTime
    azimuth_deg: AzimuthDeg
    elevation_deg: ElevationDeg
    sigma_deg: Annotated[float, Field(gt=0.0)]
    class_probs: dict[str, Probability] = Field(default_factory=dict)
    snapshot_ref: str | None = None
