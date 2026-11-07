from typing import Annotated, Literal

from pydantic import Field

from cuas.schemas.base import AzimuthDeg, Message, SimTime, Vector3


class SectorTrack(Message):
    """A heard direction that cannot be placed in 3D: a wedge from one sensor.

    It has no position, range or elevation field on purpose, so it can never claim a 3D point.
    """

    sector_id: str
    t: SimTime
    sensor_id: str
    origin_enu_m: Vector3
    bearing_deg: AzimuthDeg
    half_width_deg: Annotated[float, Field(gt=0.0, le=180.0)]
    reports: Annotated[int, Field(ge=1)]
    status: Literal["active", "lost"]
