"""The recorded clips: hashes, labels and splits. ``cuas.station`` must never import this."""

from pathlib import Path
from typing import Literal

import yaml

from cuas.config import ConfigModel

Modality = Literal["rgb", "thermal", "audio"]
Split = Literal["train", "val", "test"]
DistanceBin = Literal["close", "medium", "distant"]

MANIFEST_NAME = "media_manifest.yaml"


class ClipEntry(ConfigModel):
    """``id`` is opaque: unlike ``path``, it reveals nothing about the label."""

    id: str
    path: str
    sha256: str
    modality: Modality
    label: str
    split: Split
    group: str
    distance_bin: DistanceBin | None = None
    drone_type: str | None = None
    labels_path: str | None = None


class ExcludedEntry(ConfigModel):
    path: str
    reason: str


class MediaManifest(ConfigModel):
    source_commit: str
    same_label_scene_pairs: int
    cross_label_scene_pairs: int
    clips: tuple[ClipEntry, ...]
    excluded: tuple[ExcludedEntry, ...]


# The folder each clip's path starts with, and the dataset's name for on-screen captions.
DATASET_NAMES = {
    "svanstrom": "Svanström Drone Detection Dataset",
    "fsd50k": "FSD50K",
}


def dataset_names(manifest: MediaManifest) -> dict[str, str]:
    """Each clip's public dataset, by clip ID. Clip IDs are opaque, so this reveals no label."""
    return {c.id: DATASET_NAMES[c.path.split("/", 1)[0]] for c in manifest.clips}


def load_manifest(config_dir: Path) -> MediaManifest:
    raw = yaml.safe_load((config_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    return MediaManifest.model_validate(raw)
