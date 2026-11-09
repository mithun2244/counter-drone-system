"""The evidence store: chain maths with known answers, files and run folders."""

import hashlib
import json
from pathlib import Path

import pytest

from cuas.evidence.store import (
    CHAIN,
    EvidenceStore,
    canonical,
    fresh_run_dir,
    record_hash,
)
from cuas.schemas import EvidenceRecord, FileRef


def test_each_record_carries_the_hash_of_the_one_before(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    snapshot = store.write("evidence/0001-alert-alert-1.json", b"{}")
    first = store.append(
        "alert", 1.0, "alert-1", ("trk-1",), (snapshot,), {"level": "amber"}
    )
    second = store.append(
        "label", 2.0, "alert-1", ("trk-1",), (), {"label": "confirm"}, "req-1"
    )
    assert (first.seq, first.prev_hash) == (1, None)
    assert (second.seq, second.prev_hash) == (2, first.record_hash)
    assert snapshot.sha256 == hashlib.sha256(b"{}").hexdigest()
    lines = (tmp_path / CHAIN).read_bytes().splitlines()
    assert [EvidenceRecord.model_validate_json(line) for line in lines] == [
        first,
        second,
    ]
    assert store.head == second and store.next_seq == 3


def test_the_record_hash_is_of_the_canonical_json_without_it(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    record = store.append("label", 2.5, "alert-1", ("trk-1",), (), {"label": "dismiss"})
    line = (tmp_path / CHAIN).read_bytes().splitlines()[0]
    fields = json.loads(line)
    del fields["record_hash"]
    by_hand = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()
    assert record.record_hash == hashlib.sha256(by_hand).hexdigest()
    assert record.record_hash == record_hash(record)
    assert line == canonical(record.model_dump(mode="json"))


def test_a_run_folder_gets_one_chain_only(tmp_path: Path) -> None:
    EvidenceStore(tmp_path)
    with pytest.raises(FileExistsError):
        EvidenceStore(tmp_path)


def test_ref_hashes_a_file_already_there_or_gives_none(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    (tmp_path / "station_st1").mkdir()
    (tmp_path / "station_st1" / "clip.mp4").write_bytes(b"clip")
    assert store.ref("station_st1/clip.mp4") == FileRef(
        path="station_st1/clip.mp4", sha256=hashlib.sha256(b"clip").hexdigest()
    )
    assert store.ref("station_st1/other.mp4") is None


def test_fresh_run_folders_never_reuse_a_name(tmp_path: Path) -> None:
    assert fresh_run_dir(tmp_path, "s1_seed7").name == "s1_seed7_001"
    (tmp_path / "s1_seed7_001").mkdir()
    assert fresh_run_dir(tmp_path, "s1_seed7").name == "s1_seed7_002"
