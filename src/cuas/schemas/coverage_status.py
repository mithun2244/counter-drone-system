from typing import Annotated

from pydantic import Field

from cuas.schemas.base import Message, SimTime


class CoverageStatus(Message):
    """Share of the watched zone that enough stations can still see (design.md A10)."""

    t: SimTime
    coverage_pct: Annotated[float, Field(ge=0.0, le=100.0)]
    warning: bool
