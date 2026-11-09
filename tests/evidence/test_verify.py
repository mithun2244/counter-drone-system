"""``cuas verify`` on a finished run: it passes untouched and fails on any edit."""

import hashlib
import shutil
from pathlib import Path

import pytest

from cuas.cli import FAILED, verify
from cuas.evidence.store import CHAIN, EvidenceStore, canonical, record_hash
from cuas.evidence.verify import verify_chain
from cuas.schemas import FileRef


def stored_files(run_dir: Path) -> list[str]:
    return sorted(
        p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*") if p.is_file()
    )


def test_a_finished_run_verifies(finished_run: Path, capsys) -> None:
    report = verify_chain(finished_run)
    assert report.problems == []
    kinds = [r.kind for r in report.records]
    assert kinds == ["alert", "escalation", "label", "export", "export"]
    assert stored_files(finished_run) == [
        "evidence/0001-alert-alert-1.json",
        "evidence/0002-escalation-alert-1.json",
        "evidence/chain.jsonl",
        "handoff/alert-1-0004.json",
        "handoff/alert-1-0005.json",
        "station_st1/abcdef0123456789.mp4",
        "station_st1/hashes.json",
    ]
    assert verify(finished_run) == 0


def flip_middle_byte(data: bytes) -> bytes:
    middle = len(data) // 2
    return data[:middle] + bytes([data[middle] ^ 0x01]) + data[middle + 1 :]


@pytest.mark.parametrize(
    "edit", [flip_middle_byte, lambda data: data + b"\n"], ids=["flip", "append"]
)
def test_editing_any_stored_file_fails_verification(
    finished_run: Path, tmp_path: Path, edit, capsys
) -> None:
    for n, relative in enumerate(stored_files(finished_run)):
        copy = tmp_path / f"edited-{n}"
        shutil.copytree(finished_run, copy)
        path = copy / relative
        path.write_bytes(edit(path.read_bytes()))
        assert verify(copy) == FAILED, relative


def rewrite_chain(run_dir: Path, change) -> list[str]:
    chain = run_dir / CHAIN
    lines = chain.read_bytes().splitlines(keepends=True)
    chain.write_bytes(b"".join(change(lines)))
    return verify_chain(run_dir).problems


def test_removing_a_middle_record_breaks_the_chain(finished_run: Path) -> None:
    problems = rewrite_chain(finished_run, lambda lines: lines[:2] + lines[3:])
    assert "record 4: expected seq 3" in problems
    assert "record 4: prev_hash does not match the record before" in problems


def test_a_rewritten_record_with_a_fresh_hash_breaks_the_next_link(
    finished_run: Path,
) -> None:
    label = verify_chain(finished_run).records[2]
    forged = label.model_copy(update={"details": {"label": "dismiss"}})
    forged = forged.model_copy(update={"record_hash": record_hash(forged)})
    line = canonical(forged.model_dump(mode="json")) + b"\n"
    problems = rewrite_chain(finished_run, lambda ls: [*ls[:2], line, *ls[3:]])
    assert problems == ["record 4: prev_hash does not match the record before"]


def test_removing_the_newest_record_leaves_its_file_unlisted(
    finished_run: Path,
) -> None:
    problems = rewrite_chain(finished_run, lambda lines: lines[:-1])
    assert problems == ["handoff/alert-1-0005.json: listed by no record"]


def test_removing_the_newest_record_and_its_file_is_not_detected(
    finished_run: Path,
) -> None:
    """The documented limit: nothing outside the run anchors the head."""
    rewrite_chain(finished_run, lambda lines: lines[:-1])
    (finished_run / "handoff" / "alert-1-0005.json").unlink()
    assert verify_chain(finished_run).problems == []


def test_a_chain_line_must_stay_as_the_store_wrote_it(finished_run: Path) -> None:
    """A space changes no field, so no hash: only the byte form shows the edit."""
    problems = rewrite_chain(
        finished_run, lambda ls: [ls[0].replace(b',"', b', "', 1), *ls[1:]]
    )
    assert problems == ["evidence/chain.jsonl line 1: not as the store wrote it"]


def test_a_file_no_record_lists_fails(finished_run: Path) -> None:
    (finished_run / "handoff" / "extra.json").write_text("{}", encoding="utf-8")
    assert verify_chain(finished_run).problems == [
        "handoff/extra.json: listed by no record"
    ]


def test_a_record_cannot_list_a_file_outside_the_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    store = EvidenceStore(run_dir)
    (tmp_path / "secret.json").write_bytes(b"{}")
    outside = FileRef(path="../secret.json", sha256=hashlib.sha256(b"{}").hexdigest())
    store.append("export", 1.0, "alert-1", (), (outside,), {})
    assert verify_chain(run_dir).problems == ["../secret.json: outside the run folder"]


def test_a_run_without_a_chain_fails(tmp_path: Path) -> None:
    assert verify_chain(tmp_path).problems == [
        "no evidence chain at evidence/chain.jsonl"
    ]
