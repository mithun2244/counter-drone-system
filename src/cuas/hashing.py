"""File hashing shared by the data scripts and the local recorder."""

import hashlib
from pathlib import Path

CHUNK_BYTES = 1 << 20


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()
