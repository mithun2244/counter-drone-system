"""The ``cuas`` command."""

import subprocess
import sys
import tomllib
from pathlib import Path

from cuas.cli import FAILED, main

ROOT = Path(__file__).resolve().parents[1]


def test_verify_passes_a_finished_run_and_names_its_head(
    finished_run: Path, capsys
) -> None:
    assert main(["verify", str(finished_run)]) == 0
    out = capsys.readouterr().out
    assert "verified" in out and "5 records, 5 files, head seq 5 sha256:" in out


def test_verify_fails_on_a_changed_recording_and_says_why(
    finished_run: Path, capsys
) -> None:
    clip = finished_run / "station_st1" / "abcdef0123456789.mp4"
    clip.write_bytes(b"something else")
    assert main(["verify", str(finished_run)]) == FAILED
    out = capsys.readouterr().out
    assert out.startswith(f"FAILED {finished_run}")
    assert "station_st1/abcdef0123456789.mp4: changed since record 1" in out
    assert "hash mismatch" in out


def test_it_is_installed_as_a_console_script(finished_run: Path) -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["scripts"] == {"cuas": "cuas.cli:main"}
    result = subprocess.run(
        [sys.executable, "-m", "cuas.cli", "verify", str(finished_run)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
