"""Checks a run's evidence chain and every file it lists (``cuas verify``).

A problem is reported when a record does not parse, ``seq`` skips, a ``prev_hash`` link or a
recomputed ``record_hash`` is wrong, a listed file is missing, outside the run folder or has
changed, or a file under ``evidence/`` or ``handoff/`` is listed by no record.

Known limit: with nothing outside the run to anchor it, removing the newest records leaves a
valid shorter chain. Exports carry the chain head at the time, and the dashboard shows it.
"""

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from cuas.evidence.store import (
    CHAIN,
    EVIDENCE_DIR,
    HANDOFF_DIR,
    canonical,
    record_hash,
)
from cuas.hashing import sha256_of
from cuas.schemas import EvidenceRecord, FileRef


@dataclass
class ChainReport:
    records: list[EvidenceRecord]
    problems: list[str]


def verify_chain(run_dir: Path) -> ChainReport:
    chain = run_dir / CHAIN
    if not chain.is_file():
        return ChainReport([], [f"no evidence chain at {CHAIN}"])
    records, problems = _read(chain)
    problems += _links(records)
    for record in records:
        problems += [
            p for f in record.files if (p := _file_problem(run_dir, record, f))
        ]
    listed = {f.path for r in records for f in r.files}
    for folder in (EVIDENCE_DIR, HANDOFF_DIR):
        for path in sorted((run_dir / folder).rglob("*")):
            relative = path.relative_to(run_dir).as_posix()
            if path.is_file() and relative != CHAIN and relative not in listed:
                problems.append(f"{relative}: listed by no record")
    return ChainReport(records, problems)


def _read(chain: Path) -> tuple[list[EvidenceRecord], list[str]]:
    records, problems = [], []
    for number, line in enumerate(chain.read_bytes().splitlines(), start=1):
        try:
            record = EvidenceRecord.model_validate_json(line)
        except ValidationError as error:
            problems.append(
                f"{CHAIN} line {number}: not a record ({error.error_count()} errors)"
            )
            continue
        if line != canonical(record.model_dump(mode="json")):
            problems.append(f"{CHAIN} line {number}: not as the store wrote it")
        records.append(record)
    return records, problems


def _links(records: list[EvidenceRecord]) -> list[str]:
    problems = []
    previous: EvidenceRecord | None = None
    for record in records:
        where = f"record {record.seq}"
        expected_seq = 1 if previous is None else previous.seq + 1
        if record.seq != expected_seq:
            problems.append(f"{where}: expected seq {expected_seq}")
        expected_prev = None if previous is None else previous.record_hash
        if record.prev_hash != expected_prev:
            problems.append(f"{where}: prev_hash does not match the record before")
        if record.record_hash != record_hash(record):
            problems.append(f"{where}: record_hash does not match its content")
        previous = record
    return problems


def _file_problem(run_dir: Path, record: EvidenceRecord, ref: FileRef) -> str | None:
    path = (run_dir / ref.path).resolve()
    if not path.is_relative_to(run_dir.resolve()):
        return f"{ref.path}: outside the run folder"
    if not path.is_file():
        return f"{ref.path}: missing"
    if sha256_of(path) != ref.sha256:
        return f"{ref.path}: changed since record {record.seq}"
    return None
