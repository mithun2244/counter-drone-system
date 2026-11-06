from typing import Annotated, Literal

from pydantic import Field

from cuas.schemas.base import Message, SimTime, Vector3


class Track(Message):
    track_id: str
    t: SimTime
    position_enu_m: Vector3
    velocity_mps: Vector3
    covariance: tuple[tuple[float, ...], ...]
    n_stations: Annotated[int, Field(ge=0)]
    status: Literal["tentative", "confirmed", "lost"]
