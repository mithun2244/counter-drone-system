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
