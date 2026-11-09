"""A run's evidence store: files plus a SHA-256 hash chain (docs/design.md A11).

Layout, relative to the run folder: ``evidence/chain.jsonl`` holds one record per line,
``evidence/`` the alert snapshots and ``handoff/`` the hand-off packages. Recordings stay where
the recorder put them (``station_<id>/``), and records list them by path and hash. The chain is
append-only: each record carries the previous record's hash, so changing or removing any record
but the newest breaks it.
"""

import hashlib
import json
from itertools import count
from pathlib import Path
from typing import Any

from cuas.hashing import sha256_of
from cuas.schemas import EvidenceRecord, FileRef
from cuas.schemas.evidence_record import RecordKind

EVIDENCE_DIR = "evidence"
HANDOFF_DIR = "handoff"
CHAIN = f"{EVIDENCE_DIR}/chain.jsonl"


def canonical(fields: dict[str, Any]) -> bytes:
    """The one byte form records are hashed and stored in."""
    return json.dumps(
        fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def record_hash(record: EvidenceRecord) -> str:
    """The hash a record must carry: of its canonical JSON without ``record_hash``."""
    fields = record.model_dump(mode="json", exclude={"record_hash"})
    return hashlib.sha256(canonical(fields)).hexdigest()


def fresh_run_dir(runs_dir: Path, stem: str) -> Path:
    """The first ``<stem>_<NNN>`` not taken, so no run overwrites or mixes with another."""
    for n in count(1):
        path = runs_dir / f"{stem}_{n:03d}"
        if not path.exists():
            return path
    raise AssertionError("unreachable")


class EvidenceStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self._chain = run_dir / CHAIN
        self._chain.parent.mkdir(parents=True, exist_ok=True)
        # One chain per run folder: a folder that already has one is never appended to.
        self._chain.touch(exist_ok=False)
        self.head: EvidenceRecord | None = None

    @property
    def next_seq(self) -> int:
        return 1 if self.head is None else self.head.seq + 1

    def write(self, relative: str, data: bytes) -> FileRef:
        path = self.run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return FileRef(path=relative, sha256=hashlib.sha256(data).hexdigest())

    def ref(self, relative: str) -> FileRef | None:
        """A file already in the run folder, such as a recording, or ``None`` if absent."""
        path = self.run_dir / relative
        return (
            FileRef(path=relative, sha256=sha256_of(path)) if path.is_file() else None
        )

    def append(
        self,
        kind: RecordKind,
        t: float,
        alert_id: str,
        track_ids: tuple[str, ...],
        files: tuple[FileRef, ...],
        details: dict[str, str | float | None],
        request_id: str | None = None,
    ) -> EvidenceRecord:
        unsealed = EvidenceRecord(
            seq=self.next_seq,
            kind=kind,
            t=t,
            alert_id=alert_id,
            track_ids=track_ids,
            files=files,
            details=details,
            prev_hash=None if self.head is None else self.head.record_hash,
            request_id=request_id,
            record_hash="0" * 64,
        )
        record = unsealed.model_copy(update={"record_hash": record_hash(unsealed)})
        with self._chain.open("ab") as chain:
            chain.write(canonical(record.model_dump(mode="json")) + b"\n")
        self.head = record
        return record
