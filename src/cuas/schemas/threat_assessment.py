from typing import Annotated, Literal

from pydantic import Field

from cuas.schemas.base import Message, Probability


class ThreatAssessment(Message):
    """``zone`` is a zone ID, not a display label. Both optional fields are ``None`` if no zone is ahead."""

    track_id: str
    score: Probability
    level: Literal["red", "amber", "info"]
    zone: str | None
    time_to_impact_s: Annotated[float, Field(ge=0.0)] | None
    reasons: tuple[str, ...]
