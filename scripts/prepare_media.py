"""Build config/media_manifest.yaml from the downloaded recordings.

Applies the exclusions in data/README.md and splits by source. Writes hashes and labels only;
the media itself stays in data/.
"""

import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import av
import numpy as np
import yaml

from cuas.config import SplitSettings, load_site
from cuas.hashing import sha256_of
from cuas.media_manifest import MANIFEST_NAME
from cuas.metrics.mat_labels import read_label_file
from cuas.metrics.splits import (
    Clip,
    Group,
    assign_splits,
    drop_exact_copies,
    fixed_blocks,
    lookalike_pairs,
    scene_groups,
    splits_too_thin,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
SVANSTROM = "svanstrom/Data"
SVANSTROM_COMMIT = "442d0c6750708cc221636f7a1fd31cbd8cb0aeb8"
SPREADSHEET_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
SOURCE_COLUMN = "DRONE TYPE / INTERNET SOURCE"

# A difference hash of frames spread through the clip: 8 x 8 bits for each of 4 frames.
HASH_ROWS = 8
HASH_COLUMNS = 9
SIGNATURE_POSITIONS = (0.0, 1 / 3, 2 / 3, 1.0)

VIDEO_FOLDERS = {"IR": "Video_IR", "V": "Video_V"}
MODALITIES = {"IR": "thermal", "V": "rgb"}
AUDIO_CLASSES = {"DRONE": "electric_drone", "BACKGROUND": "background"}
ENGINE_LABEL = "engine"
FSD50K = "fsd50k"
UPLOADER_HASH_CHARS = 10
EXCLUDED_AUDIO_REASON = "helicopter audio may come from third-party YouTube videos"
EXCLUDED_VIDEO_REASON = "third-party internet source, rights unverified"
EXCLUDED_LABELS_REASON = "label file layout could not be read"
REQUIRED_CLIPS = tuple(
    (modality, label)
    for modality in MODALITIES.values()
    for label in ("drone", "bird", "airplane", "helicopter")
) + tuple(("audio", label) for label in (*AUDIO_CLASSES.values(), ENGINE_LABEL))


def read_description(path: Path) -> list[dict[str, str]]:
    """Read the description spreadsheet using the standard library; .xlsx is zipped XML."""
    with zipfile.ZipFile(path) as book:
        shared = [
            "".join(t.text or "" for t in item.iter(f"{{{SPREADSHEET_NS['m']}}}t"))
            for item in ET.fromstring(book.read("xl/sharedStrings.xml"))
        ]
        sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
    rows = [
        {
            re.match(r"[A-Z]+", cell.get("r", "")).group(): _cell_value(cell, shared)
            for cell in row
            if cell.find("m:v", SPREADSHEET_NS) is not None
        }
        for row in sheet.find("m:sheetData", SPREADSHEET_NS)
    ]
    header = {column: " ".join(name.split()) for column, name in rows[0].items()}
    return [
        {header[column]: value for column, value in row.items() if column in header}
        for row in rows[1:]
    ]


def _cell_value(cell: ET.Element, shared: list[str]) -> str:
    value = cell.find("m:v", SPREADSHEET_NS).text or ""
    return shared[int(value)] if cell.get("t") == "s" else value


def video_path(row: dict[str, str]) -> str:
    sensor, name, number = row["SENSOR"], row["CLASS"], int(float(row["NUMBER"]))
    return f"{SVANSTROM}/{VIDEO_FOLDERS[sensor]}/{sensor}_{name}_{number:03d}.mp4"


def difference_hash(gray: np.ndarray) -> np.ndarray:
    """Whether each cell is brighter than its left neighbour, which ignores overall exposure."""
    grid = np.array(
        [
            [cell.mean() for cell in np.array_split(row, HASH_COLUMNS, axis=1)]
            for row in np.array_split(gray, HASH_ROWS, axis=0)
        ]
    )
    return (grid[:, 1:] > grid[:, :-1]).ravel()


def inspect_clip(path: Path) -> tuple[np.ndarray, int]:
    """A hash of frames across the clip, and its length. One frame mostly captures framing."""
    with av.open(str(path)) as container:
        frames = list(container.decode(video=0))
    picks = [frames[int(q * (len(frames) - 1))] for q in SIGNATURE_POSITIONS]
    signature = np.concatenate(
        [difference_hash(f.to_ndarray(format="gray")) for f in picks]
    )
    return signature, len(frames)


def labels_readable(path: Path, count: int) -> bool:
    try:
        read_label_file(path, count)
    except ValueError:
        return False
    return True


def build_video(
    rows: list[dict[str, str]],
    settings: SplitSettings,
    signatures: dict[str, np.ndarray],
    unreadable: frozenset[str] = frozenset(),
) -> tuple[list[dict], list[dict]]:
    """Group by scene within each sensor and class, and split those groups."""
    excluded = []
    kept: list[dict[str, str]] = []
    clips: defaultdict[str, list[Clip]] = defaultdict(list)
    for row in rows:
        path = video_path(row)
        if "youtube" in row.get(SOURCE_COLUMN, "").lower():
            excluded.append({"path": path, "reason": EXCLUDED_VIDEO_REASON})
            continue
        if path in unreadable:
            excluded.append({"path": path, "reason": EXCLUDED_LABELS_REASON})
            continue
        kept.append(row)
        source = f"{row['DISTANCE BIN']}|{row.get(SOURCE_COLUMN, '')}"
        stratum = f"{row['SENSOR']}|{row['CLASS']}"
        clips[f"{row['SENSOR']}_{row['CLASS']}"].append(
            Clip(path, int(float(row["NUMBER"])), stratum, source)
        )
    groups: list[Group] = []
    for prefix, members in sorted(clips.items()):
        groups.extend(
            scene_groups(members, signatures, settings.scene_max_hamming, prefix)
        )
    assigned = assign_splits(groups, settings.fractions, settings.salt)
    group_of = {clip.id: group.id for group in groups for clip in group.clips}
    entries = [
        _video_entry(
            row, group_of[video_path(row)], assigned[group_of[video_path(row)]]
        )
        for row in kept
    ]
    return entries, excluded


def _video_entry(row: dict[str, str], group: str, split: str) -> dict:
    relative = video_path(row)
    digest = sha256_of(DATA_DIR / relative)
    return {
        "id": digest[:16],
        "path": relative,
        "sha256": digest,
        "modality": MODALITIES[row["SENSOR"]],
        "label": row["CLASS"].lower(),
        "split": split,
        "group": group,
        "distance_bin": row["DISTANCE BIN"].lower(),
        "drone_type": row.get(SOURCE_COLUMN) or None,
        "labels_path": relative.replace(".mp4", "_LABELS.mat"),
    }


def build_audio(settings: SplitSettings) -> tuple[list[dict], list[dict]]:
    folder = DATA_DIR / SVANSTROM / "Audio"
    excluded = [
        {"path": f"{SVANSTROM}/Audio/{path.name}", "reason": EXCLUDED_AUDIO_REASON}
        for path in sorted(folder.glob("HELICOPTER_*.wav"))
    ]
    entries = []
    for name, label in sorted(AUDIO_CLASSES.items()):
        paths = {
            int(p.stem.rsplit("_", 1)[1]): p
            for p in sorted(folder.glob(f"{name}_*.wav"))
        }
        clips = [Clip(paths[n].name, n, f"audio|{name}") for n in paths]
        groups = fixed_blocks(clips, settings.audio_block_clips, f"audio_{name}")
        assigned = assign_splits(groups, settings.fractions, settings.salt)
        for group in groups:
            for clip in group.clips:
                entries.append(
                    _audio_entry(
                        paths[clip.number], label, group.id, assigned[group.id]
                    )
                )
    return entries, excluded


def build_engine(settings: SplitSettings) -> list[dict]:
    """The FSD50K proxy clips. No uploader spans two splits; only a hash of their name is kept."""
    selection = json.loads(
        (DATA_DIR / FSD50K / "selected.json").read_text(encoding="utf-8")
    )
    by_uploader: defaultdict[str, list[dict]] = defaultdict(list)
    for clip in selection:
        by_uploader[clip["uploader"]].append(clip)
    stratum = f"audio|{ENGINE_LABEL}"
    groups = []
    for uploader, clips in sorted(by_uploader.items()):
        digest = hashlib.sha256(uploader.encode()).hexdigest()[:UPLOADER_HASH_CHARS]
        members = tuple(Clip(c["fname"], int(c["fname"]), stratum) for c in clips)
        groups.append(Group(f"audio_{ENGINE_LABEL}_{digest}", stratum, members))
    assigned = assign_splits(groups, settings.fractions, settings.salt)
    entries = []
    for group in groups:
        for clip in group.clips:
            path = DATA_DIR / FSD50K / f"{clip.id}.wav"
            entry = _audio_entry(path, ENGINE_LABEL, group.id, assigned[group.id])
            entry["path"] = f"{FSD50K}/{path.name}"
            entries.append(entry)
    return entries


def _audio_entry(path: Path, label: str, group: str, split: str) -> dict:
    digest = sha256_of(path)
    return {
        "id": digest[:16],
        "path": f"{SVANSTROM}/Audio/{path.name}",
        "sha256": digest,
        "modality": "audio",
        "label": label,
        "split": split,
        "group": group,
    }


def count_lookalikes(
    entries: list[dict], signatures: dict[str, np.ndarray], max_hamming: int
) -> tuple[int, int]:
    """Train and test clips showing the same scene: with the same label, then across labels.

    The first must be zero by construction. The second is reported, because a shared sky is
    not the same leak as a shared target.
    """
    same_label, other_label = 0, 0
    by_id = {e["id"]: e for e in entries if e["modality"] != "audio"}
    by_signature = {e["id"]: signatures[e["path"]] for e in by_id.values()}
    splits = {e["id"]: e["split"] for e in by_id.values()}
    for a, b in lookalike_pairs(by_signature, splits, "train", "test", max_hamming):
        if by_id[a]["modality"] != by_id[b]["modality"]:
            continue
        if by_id[a]["label"] == by_id[b]["label"]:
            same_label += 1
        else:
            other_label += 1
    return same_label, other_label


def summarise(entries: list[dict]) -> dict[tuple[str, str], Counter[str]]:
    counts: defaultdict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for entry in entries:
        counts[(entry["modality"], entry["label"])][entry["split"]] += 1
    return dict(counts)


def main() -> int:
    settings = load_site(CONFIG_DIR).station_ai.split
    rows = read_description(DATA_DIR / SVANSTROM / "Video_dataset_description.xlsx")
    usable = [
        video_path(row)
        for row in rows
        if "youtube" not in row.get(SOURCE_COLUMN, "").lower()
    ]
    inspected = {path: inspect_clip(DATA_DIR / path) for path in usable}
    signatures = {path: found[0] for path, found in inspected.items()}
    unreadable = frozenset(
        path
        for path, found in inspected.items()
        if not labels_readable(DATA_DIR / path.replace(".mp4", "_LABELS.mat"), found[1])
    )
    video, excluded_video = build_video(rows, settings, signatures, unreadable)
    audio, excluded_audio = build_audio(settings)
    entries, copies = drop_exact_copies(video + audio + build_engine(settings))
    excluded = excluded_video + excluded_audio + copies
    counts = summarise(entries)
    for key, tally in sorted(counts.items()):
        print(f"{key[0]:8} {key[1]:15} {dict(sorted(tally.items()))}")
    missing = [pair for pair in REQUIRED_CLIPS if pair not in counts]
    if missing:
        print("no clips left for:", *missing, sep="\n  ")
        return 1
    thin = splits_too_thin(counts, "test", settings.min_test_clips)
    if thin:
        print("too few held-out clips:", *thin, sep="\n  ")
        return 1
    same_label, other_label = count_lookalikes(
        entries, signatures, settings.scene_max_hamming
    )
    print(f"{len(entries)} clips kept, {len(excluded)} excluded")
    print(f"same-scene pairs across train and test, same label: {same_label}")
    print(f"same-scene pairs across train and test, other label: {other_label}")
    if same_label:
        print("a scene crosses train and test")
        return 1
    manifest = {
        "source_commit": SVANSTROM_COMMIT,
        "same_label_scene_pairs": same_label,
        "cross_label_scene_pairs": other_label,
        "clips": entries,
        "excluded": sorted(excluded, key=lambda e: e["path"]),
    }
    text = yaml.safe_dump(
        manifest, sort_keys=False, default_flow_style=None, width=1000
    )
    (CONFIG_DIR / MANIFEST_NAME).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
