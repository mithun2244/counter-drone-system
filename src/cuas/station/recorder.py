"""Local recorder: keeps each recording used, with a SHA-256 per file (docs/design.md A3).

File names are opaque, so nothing here reveals what a recording shows.
"""

import hashlib
import json
from pathlib import Path

from cuas.hashing import sha256_of

HASHES_NAME = "hashes.json"
STATION_PREFIX = "station_"


class Recorder:
    def __init__(self, run_dir: Path) -> None:
        self._run_dir = run_dir

    def save(self, sensor_owner: str, clip_id: str, suffix: str, data: bytes) -> str:
        """Store one recording for a station or picket and return its hash."""
        folder = self._run_dir / f"{STATION_PREFIX}{sensor_owner}"
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{clip_id}{suffix}"
        (folder / name).write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        hashes_path = folder / HASHES_NAME
        hashes = (
            json.loads(hashes_path.read_text(encoding="utf-8"))
            if hashes_path.exists()
            else {}
        )
        hashes[name] = digest
        hashes_path.write_text(_hashes_text(hashes), encoding="utf-8")
        return digest


def _hashes_text(hashes: dict[str, str]) -> str:
    return json.dumps(hashes, indent=1, sort_keys=True)


def verify_recordings(run_dir: Path) -> list[str]:
    """Every recording that is missing or has changed, and every hash list changed since the
    recorder wrote it. Empty means all is as recorded."""
    problems: list[str] = []
    for hashes_path in sorted(run_dir.glob(f"{STATION_PREFIX}*/{HASHES_NAME}")):
        try:
            text = hashes_path.read_text(encoding="utf-8")
            hashes = json.loads(text)
            if not isinstance(hashes, dict) or text != _hashes_text(hashes):
                raise ValueError("not as the recorder wrote it")
        except ValueError:
            problems.append(f"hash list changed: {hashes_path}")
            continue
        for name, digest in sorted(hashes.items()):
            path = hashes_path.parent / name
            if not path.exists():
                problems.append(f"missing: {path}")
            elif sha256_of(path) != digest:
                problems.append(f"hash mismatch: {path}")
    return problems
