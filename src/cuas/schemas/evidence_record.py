from typing import Annotated, Literal

from pydantic import Field

from cuas.schemas.base import Message, SimTime

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
RecordKind = Literal["alert", "escalation", "label", "export"]


class FileRef(Message):
    """A stored file, by its path relative to the run folder, and its SHA-256."""

    path: str
    sha256: Sha256Hex


class EvidenceRecord(Message):
    """One link of a run's evidence chain (``evidence/chain.jsonl``, docs/design.md A11).

    ``record_hash`` is the SHA-256 of the record's canonical JSON without it, and
    ``prev_hash`` is the previous record's ``record_hash``: ``None`` only for ``seq`` 1.
    ``request_id`` names the operator request that caused the record, if one did.
    """

    seq: Annotated[int, Field(ge=1)]
    kind: RecordKind
    t: SimTime
    alert_id: str
    track_ids: tuple[str, ...]
    files: tuple[FileRef, ...]
    details: dict[str, str | float | None]
    prev_hash: Sha256Hex | None
    request_id: str | None = None
    record_hash: Sha256Hex
