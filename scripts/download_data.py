"""Fetch the public recordings and starting weights. Licences and rights: data/README.md.

Downloads are pinned and hashed. ``--verify`` re-checks everything already on disk.
"""

import argparse
import hashlib
import io
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PRETRAINED_DIR = ROOT / "models" / "pretrained"
MANIFEST_PATH = ROOT / "config" / "media_manifest.yaml"

SVANSTROM_REPO = "DroneDetectionThesis/Drone-detection-dataset"
SVANSTROM_COMMIT = "442d0c6750708cc221636f7a1fd31cbd8cb0aeb8"
SVANSTROM_DIR = DATA_DIR / "svanstrom"
SVANSTROM_LICENCE_SHA256 = (
    "a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499"
)
# Only the media, the labels and the terms are kept. The archive's .m script is left behind.
SVANSTROM_KEEP = ("Data/", "LICENSE", "README.md")

SSDLITE_NAME = "ssdlite320_mobilenet_v3_large_coco-a79551df.pth"
SSDLITE_URL = f"https://download.pytorch.org/models/{SSDLITE_NAME}"
SSDLITE_SHA256_PREFIX = "a79551df"

CHUNK_BYTES = 1 << 20


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract(archive: zipfile.ZipFile, keep: tuple[str, ...], dest: Path) -> int:
    """Extract kept members, dropping the archive's top folder. The archive is untrusted."""
    dest = dest.resolve()
    count = 0
    for member in archive.infolist():
        relative = member.filename.split("/", 1)[-1]
        if member.is_dir() or not relative.startswith(keep):
            continue
        target = (dest / relative).resolve()
        if not target.is_relative_to(dest):
            raise ValueError(f"unsafe path in archive: {member.filename}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source, target.open("wb") as out:
            shutil.copyfileobj(source, out)
        count += 1
    return count


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=300) as response:
        return response.read()


def fetch_svanstrom() -> None:
    if (SVANSTROM_DIR / "LICENSE").exists():
        print(f"already present: {SVANSTROM_DIR}")
        return
    url = f"https://codeload.github.com/{SVANSTROM_REPO}/zip/{SVANSTROM_COMMIT}"
    print(f"downloading {url}")
    with zipfile.ZipFile(io.BytesIO(download(url))) as archive:
        count = safe_extract(archive, SVANSTROM_KEEP, SVANSTROM_DIR)
    print(f"extracted {count} files to {SVANSTROM_DIR}")


def fetch_ssdlite() -> None:
    path = PRETRAINED_DIR / SSDLITE_NAME
    if path.exists():
        print(f"already present: {path}")
        return
    print(f"downloading {SSDLITE_URL}")
    PRETRAINED_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(download(SSDLITE_URL))


def verify() -> list[str]:
    """Every problem found on disk, empty when all hashes match."""
    problems: list[str] = []
    licence = SVANSTROM_DIR / "LICENSE"
    if not licence.exists():
        problems.append(f"missing: {licence}")
    elif sha256_of(licence) != SVANSTROM_LICENCE_SHA256:
        problems.append(f"licence changed: {licence}")
    weights = PRETRAINED_DIR / SSDLITE_NAME
    if not weights.exists():
        problems.append(f"missing: {weights}")
    elif not sha256_of(weights).startswith(SSDLITE_SHA256_PREFIX):
        problems.append(f"hash mismatch: {weights}")
    if MANIFEST_PATH.exists():
        problems.extend(
            verify_manifest(yaml.safe_load(MANIFEST_PATH.read_text("utf-8")))
        )
    return problems


def verify_manifest(manifest: dict) -> list[str]:
    problems: list[str] = []
    for clip in manifest["clips"]:
        path = DATA_DIR / clip["path"]
        if not path.exists():
            problems.append(f"missing: {path}")
        elif sha256_of(path) != clip["sha256"]:
            problems.append(f"hash mismatch: {path}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--verify", action="store_true", help="only check files on disk"
    )
    args = parser.parse_args()
    if not args.verify:
        fetch_svanstrom()
        fetch_ssdlite()
    problems = verify()
    for problem in problems:
        print(problem)
    print("verified" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
