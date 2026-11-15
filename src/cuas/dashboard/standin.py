"""Stand-in footage for the Zoom tab on big-drone cues: real footage of a fixed-wing drone,
never of the simulated track. Display only; nothing here reaches tracking, alerts or evidence.
"""

import hashlib
import logging
from pathlib import Path
from typing import Literal

import yaml

from cuas.config import ConfigModel

STANDIN_NAME = "standin_media.yaml"
log = logging.getLogger(__name__)


class StandIn(ConfigModel):
    """One clip and where it came from; the page builds its caption from these fields."""

    type: Literal["STAND-IN"]
    title: str
    source: str
    author: str
    licence: str
    source_title: str
    source_url: str
    downloaded: str
    edits: str
    path: str
    sha256: str


def load_standin(config_dir: Path, data_dir: Path) -> tuple[StandIn, Path] | None:
    """The entry and its file, or None when this machine lacks the file as recorded."""
    listing = config_dir / STANDIN_NAME
    if not listing.is_file():
        return None
    entry = StandIn.model_validate(
        yaml.safe_load(listing.read_text(encoding="utf-8"))["standin"]
    )
    clip = data_dir / entry.path
    if not clip.is_file():
        return None
    if hashlib.sha256(clip.read_bytes()).hexdigest() != entry.sha256:
        log.warning("stand-in clip %s does not match its recorded hash: not used", clip)
        return None
    return entry, clip
