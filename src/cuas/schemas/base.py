"""Base type and shared field types for every message on the bus."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

AzimuthDeg = Annotated[float, Field(ge=0.0, lt=360.0)]
ElevationDeg = Annotated[float, Field(ge=-90.0, le=90.0)]
Probability = Annotated[float, Field(ge=0.0, le=1.0)]
SimTime = Annotated[float, Field(ge=0.0)]
Vector3 = tuple[float, float, float]


class Message(BaseModel):
    """Frozen and strict: unknown fields, type coercion and NaN are all rejected."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", strict=True, allow_inf_nan=False
    )
