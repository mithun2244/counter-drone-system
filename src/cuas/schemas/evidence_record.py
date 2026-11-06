from typing import Annotated

from pydantic import Field

from cuas.schemas.base import Message

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class EvidenceRecord(Message):
    """``prev_hash`` is ``None`` only for the first record in a chain."""

    alert_id: str
    track_id: str
    clip_path: str
    sha256: Sha256Hex
    prev_hash: Sha256Hex | None
