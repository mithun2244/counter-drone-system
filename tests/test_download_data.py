import hashlib
import importlib.util
import io
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "download_data.py"


@pytest.fixture
def module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("download_data", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def archive_with(*names: str) -> zipfile.ZipFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, name)
    return zipfile.ZipFile(buffer)


def test_extract_keeps_only_listed_members_without_the_top_folder(
    module: ModuleType, tmp_path: Path
) -> None:
    archive = archive_with("top/Data/a.wav", "top/LICENSE", "top/run_me.m")
    assert module.safe_extract(archive, ("Data/", "LICENSE"), tmp_path) == 2
    assert (tmp_path / "Data" / "a.wav").exists()
    assert (tmp_path / "LICENSE").exists()
    assert not (tmp_path / "run_me.m").exists()


def test_extract_refuses_paths_that_escape_the_folder(
    module: ModuleType, tmp_path: Path
) -> None:
    dest = tmp_path / "dest"
    archive = archive_with("top/Data/../../../escaped.txt")
    with pytest.raises(ValueError, match="unsafe path"):
        module.safe_extract(archive, ("Data/",), dest)
    assert not (tmp_path / "escaped.txt").exists()


def test_sha256_matches_a_known_answer(module: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(b"abc")
    expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert module.sha256_of(path) == expected == hashlib.sha256(b"abc").hexdigest()


def test_verify_manifest_reports_changed_and_missing_files(
    module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    (tmp_path / "good.mp4").write_bytes(b"good")
    (tmp_path / "bad.mp4").write_bytes(b"changed")
    manifest = {
        "clips": [
            {"path": "good.mp4", "sha256": hashlib.sha256(b"good").hexdigest()},
            {"path": "bad.mp4", "sha256": hashlib.sha256(b"original").hexdigest()},
            {"path": "gone.mp4", "sha256": "0" * 64},
        ]
    }
    problems = module.verify_manifest(manifest)
    assert len(problems) == 2
    assert any("hash mismatch" in p and "bad.mp4" in p for p in problems)
    assert any("missing" in p and "gone.mp4" in p for p in problems)


def in_memory_zip(files: dict[str, bytes], method: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=method) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def reader_over(blob: bytes):
    return lambda offset, size: blob[offset : offset + size]


FILES = {"a/first.wav": b"first" * 2000, "a/second.wav": b"second" * 3000}


@pytest.mark.parametrize("method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_directory_and_members_read_back_exactly(
    module: ModuleType, method: int
) -> None:
    blob = in_memory_zip(FILES, method)
    read = reader_over(blob)
    directory = module.read_directory(read, [len(blob)])
    assert set(directory) == set(FILES)
    for name, data in FILES.items():
        assert module.read_member(read, [len(blob)], directory[name]) == data


def test_a_corrupted_member_fails_its_checksum(module: ModuleType) -> None:
    blob = bytearray(in_memory_zip(FILES, zipfile.ZIP_STORED))
    read = reader_over(bytes(blob))
    member = module.read_directory(read, [len(blob)])["a/second.wav"]
    position = blob.find(b"second" * 10)
    blob[position] ^= 0xFF
    with pytest.raises(ValueError, match="checksum"):
        module.read_member(reader_over(bytes(blob)), [len(blob)], member)


def test_a_member_offset_counts_from_the_start_of_its_own_disk(
    module: ModuleType,
) -> None:
    """The archive's second file holds this member, so earlier files shift its position."""
    blob = in_memory_zip({"x.wav": b"data" * 100}, zipfile.ZIP_STORED)
    padding = b"\0" * 1000
    read = reader_over(padding + blob)
    member = module.read_directory(reader_over(blob), [len(blob)])["x.wav"]
    moved = module.Member(
        member.name, member.method, member.crc, member.compressed, 1, member.offset
    )
    assert module.read_member(read, [len(padding), len(blob)], moved) == b"data" * 100


def test_something_that_is_not_a_zip_is_refused(module: ModuleType) -> None:
    with pytest.raises(ValueError, match="end record"):
        module.read_directory(reader_over(b"not a zip"), [9])


def test_remote_parts_read_across_a_file_boundary(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    contents = {"one": b"abcde", "two": b"fghij"}
    monkeypatch.setattr(
        module.RemoteParts, "_size", lambda self, url: len(contents[url])
    )
    monkeypatch.setattr(
        module.RemoteParts,
        "_range",
        lambda self, url, start, size: contents[url][start : start + size],
    )
    parts = module.RemoteParts(["one", "two"])
    assert parts.read(3, 4) == b"defg"
    assert parts.read(0, 2) == b"ab"
    assert parts.read(6, 2) == b"gh"


CC0 = "http://creativecommons.org/publicdomain/zero/1.0/"
BY = "http://creativecommons.org/licenses/by/3.0/"


def test_only_cc0_engine_clips_without_speech_are_selected(module: ModuleType) -> None:
    rows = [
        {"fname": "1", "labels": "Engine,Vehicle"},
        {"fname": "2", "labels": "Engine,Human_voice,Speech"},
        {"fname": "3", "labels": "Bird"},
        {"fname": "4", "labels": "Engine"},
    ]
    info = {
        "1": {"license": CC0, "uploader": "a"},
        "2": {"license": CC0, "uploader": "b"},
        "3": {"license": CC0, "uploader": "c"},
        "4": {"license": BY, "uploader": "d"},
    }
    assert [c["fname"] for c in module.select_clips(rows, info)] == ["1"]
