"""Fetch the public recordings and starting weights. Licences and rights: data/README.md.

Downloads are pinned and hashed. ``--verify`` re-checks everything already on disk.

FSD50K is a 6.2 GB archive split across two files, of which only a few hundred clips are wanted.
Its files accept range requests, so the wanted clips are read straight out of the archive. Python's
``zipfile`` refuses multi-part archives, so the small reader for that format is here.
"""

import argparse
import csv
import io
import json
import shutil
import struct
import sys
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from cuas.hashing import sha256_of

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


FSD50K_DIR = DATA_DIR / "fsd50k"
FSD50K_SELECTION = FSD50K_DIR / "selected.json"
FSD50K_URL = "https://zenodo.org/records/4060432/files/"
FSD50K_PARTS = ("FSD50K.eval_audio.z01", "FSD50K.eval_audio.zip")
FSD50K_LABEL = "Engine"
FSD50K_EXCLUDED_LABELS = {"Human_voice", "Speech"}  # recorded speech is not wanted here
CC0_MARK = "publicdomain/zero"
RATE_LIMITED = 429
RETRY_DEFAULT_S = 60
RETRIES = 8

END_RECORD = b"PK\x05\x06"
ZIP64_LOCATOR = b"PK\x06\x07"
CENTRAL_HEADER = b"PK\x01\x02"
LOCAL_HEADER = b"PK\x03\x04"
END_SEARCH_BYTES = 70_000
LOCATOR_BYTES = 20
CENTRAL_FORMAT = "<4s6H3I5H2I"
LOCAL_FORMAT = "<4s5H3I2H"
ZIP64_END_FORMAT = "<4sQ2H2I4Q"
ZIP64_EXTRA_ID = 1
UNSET_32 = 0xFFFFFFFF
RAW_DEFLATE = -15
METHOD_STORED = 0
LOCAL_SLACK_BYTES = 4096

Reader = Callable[[int, int], bytes]


@dataclass(frozen=True)
class Member:
    name: str
    method: int
    crc: int
    compressed: int
    disk: int
    offset: int


def read_directory(read: Reader, sizes: Sequence[int]) -> dict[str, Member]:
    """Every file in a possibly multi-part zip, from its central directory."""
    total = sum(sizes)
    tail_start = max(total - END_SEARCH_BYTES, 0)
    tail = read(tail_start, total - tail_start)
    end = tail.rfind(END_RECORD)
    if end < 0:
        raise ValueError("no zip end record found")
    locator = tail[end - LOCATOR_BYTES : end] if end >= LOCATOR_BYTES else b""
    if locator.startswith(ZIP64_LOCATOR):
        _, disk, offset, _ = struct.unpack("<4sIQI", locator)
        start = sum(sizes[:disk]) + offset
        size = struct.calcsize(ZIP64_END_FORMAT)
        fields = struct.unpack(ZIP64_END_FORMAT, read(start, size))
        directory_disk, entries, directory_size, directory_offset = (
            fields[5],
            fields[7],
            fields[8],
            fields[9],
        )
    else:
        fields = struct.unpack("<4s4H2IH", tail[end : end + 22])
        directory_disk, entries, directory_size, directory_offset = (
            fields[2],
            fields[4],
            fields[5],
            fields[6],
        )
    start = sum(sizes[:directory_disk]) + directory_offset
    return _parse_directory(read(start, directory_size), entries)


def _parse_directory(directory: bytes, entries: int) -> dict[str, Member]:
    members: dict[str, Member] = {}
    position = 0
    fixed = struct.calcsize(CENTRAL_FORMAT)
    for _ in range(entries):
        fields = struct.unpack_from(CENTRAL_FORMAT, directory, position)
        if fields[0] != CENTRAL_HEADER:
            raise ValueError("damaged zip central directory")
        method, crc, compressed, plain = fields[4], fields[7], fields[8], fields[9]
        name_size, extra_size, comment_size = fields[10], fields[11], fields[12]
        disk, offset = fields[13], fields[16]
        name = directory[position + fixed : position + fixed + name_size].decode()
        extra_start = position + fixed + name_size
        extra = directory[extra_start : extra_start + extra_size]
        plain, compressed, offset, disk = _apply_zip64(
            extra, plain, compressed, offset, disk
        )
        members[name] = Member(name, method, crc, compressed, disk, offset)
        position = extra_start + extra_size + comment_size
    return members


def _apply_zip64(
    extra: bytes, plain: int, compressed: int, offset: int, disk: int
) -> tuple[int, int, int, int]:
    """Sizes too big for the main record live in an extra block, in this fixed order."""
    position = 0
    while position + 4 <= len(extra):
        block, size = struct.unpack_from("<2H", extra, position)
        if block == ZIP64_EXTRA_ID:
            values = list(struct.unpack_from(f"<{size // 8}Q", extra, position + 4))
            if plain == UNSET_32:
                plain = values.pop(0)
            if compressed == UNSET_32:
                compressed = values.pop(0)
            if offset == UNSET_32:
                offset = values.pop(0)
        position += 4 + size
    return plain, compressed, offset, disk


def read_member(read: Reader, sizes: Sequence[int], member: Member) -> bytes:
    """One file's bytes. Its checksum is verified, so a bad read cannot go unnoticed."""
    start = sum(sizes[: member.disk]) + member.offset
    fixed = struct.calcsize(LOCAL_FORMAT)
    blob = read(start, fixed + member.compressed + LOCAL_SLACK_BYTES)
    fields = struct.unpack_from(LOCAL_FORMAT, blob, 0)
    if fields[0] != LOCAL_HEADER:
        raise ValueError(f"no local header for {member.name}")
    data_start = fixed + fields[9] + fields[10]
    raw = blob[data_start : data_start + member.compressed]
    data = raw if member.method == METHOD_STORED else zlib.decompress(raw, RAW_DEFLATE)
    if zlib.crc32(data) != member.crc:
        raise ValueError(f"checksum mismatch for {member.name}")
    return data


class RemoteParts:
    """Reads a span of bytes across the archive's files, using range requests."""

    def __init__(self, urls: Sequence[str]) -> None:
        self._urls = urls
        self.sizes = [self._size(url) for url in urls]

    def _size(self, url: str) -> int:
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=60) as response:
            return int(response.headers["Content-Length"])

    def read(self, offset: int, size: int) -> bytes:
        chunks = []
        for url, part_size in zip(self._urls, self.sizes, strict=True):
            if offset < part_size and size > 0:
                take = min(size, part_size - offset)
                chunks.append(self._range(url, offset, take))
                size -= take
                offset = 0
            else:
                offset = max(offset - part_size, 0)
        return b"".join(chunks)

    def _range(self, url: str, start: int, size: int) -> bytes:
        headers = {"Range": f"bytes={start}-{start + size - 1}"}
        request = urllib.request.Request(url, headers=headers)
        for _ in range(RETRIES):
            try:
                with urllib.request.urlopen(request, timeout=300) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                if error.code != RATE_LIMITED:
                    raise
                time.sleep(int(error.headers.get("Retry-After") or RETRY_DEFAULT_S))
        raise RuntimeError(f"still rate limited after {RETRIES} tries: {url}")


def select_clips(rows: Sequence[dict[str, str]], info: dict[str, dict]) -> list[dict]:
    """CC0 clips labelled Engine, without recorded speech."""
    selected = []
    for row in rows:
        labels = set(row["labels"].split(","))
        details = info[row["fname"]]
        if (
            FSD50K_LABEL in labels
            and not labels & FSD50K_EXCLUDED_LABELS
            and CC0_MARK in details["license"]
        ):
            selected.append(
                {
                    "fname": row["fname"],
                    "license": details["license"],
                    "uploader": details["uploader"],
                }
            )
    return selected


def fetch_fsd50k() -> None:
    if FSD50K_SELECTION.exists():
        print(f"already present: {FSD50K_DIR}")
        return
    truth = zipfile.ZipFile(
        io.BytesIO(download(FSD50K_URL + "FSD50K.ground_truth.zip"))
    )
    meta = zipfile.ZipFile(io.BytesIO(download(FSD50K_URL + "FSD50K.metadata.zip")))
    rows = list(
        csv.DictReader(
            io.TextIOWrapper(
                truth.open("FSD50K.ground_truth/eval.csv"), encoding="utf-8"
            )
        )
    )
    info = json.load(meta.open("FSD50K.metadata/eval_clips_info_FSD50K.json"))
    selected = select_clips(rows, info)
    print(f"{len(selected)} clips selected")
    parts = RemoteParts([FSD50K_URL + part for part in FSD50K_PARTS])
    directory = read_directory(parts.read, parts.sizes)
    by_stem = {Path(name).stem: member for name, member in directory.items()}
    FSD50K_DIR.mkdir(parents=True, exist_ok=True)
    for position, clip in enumerate(selected, start=1):
        target = FSD50K_DIR / f"{clip['fname']}.wav"
        if not target.exists():
            target.write_bytes(
                read_member(parts.read, parts.sizes, by_stem[clip["fname"]])
            )
        if position % 25 == 0:
            print(f"{position}/{len(selected)}", flush=True)
    FSD50K_SELECTION.write_text(json.dumps(selected, indent=1), encoding="utf-8")


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
    parser.add_argument(
        "--fsd50k", action="store_true", help="also fetch the FSD50K engine clips"
    )
    args = parser.parse_args()
    if not args.verify:
        fetch_svanstrom()
        fetch_ssdlite()
        if args.fsd50k:
            fetch_fsd50k()
    problems = verify()
    for problem in problems:
        print(problem)
    print("verified" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
