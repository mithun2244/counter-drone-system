"""Real video for the camera tabs, and which scenarios the demo lists.

Display clips are real footage of drones, never of the simulated track: a ``STAND-IN`` (a clip
of a similar aircraft from outside the datasets) or a ``SAMPLE`` (a public dataset clip). The
page captions each from its entry. Display only; nothing here reaches tracking, alerts or
evidence.
"""

import hashlib
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import Field

from cuas.config import ConfigModel, DemoScenario
from cuas.dashboard.contract import ScenarioChoice, SiteProfile

DISPLAY_NAME = "display_clips.yaml"
Camera = Literal["wide", "zoom"]
log = logging.getLogger(__name__)


class StandInClip(ConfigModel):
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

    def caption(self) -> str:
        return (
            f"Stand-in clip: {self.title} - {self.source}, {self.author}, "
            f"{self.licence} - not footage of this track"
        )


class SampleClip(ConfigModel):
    type: Literal["SAMPLE"]
    dataset: str
    source_title: str
    """The dataset's own name for the clip, for example ``V_DRONE_040``."""
    path: str
    sha256: str

    def caption(self) -> str:
        return f"Sample clip from {self.dataset} - not footage of this track"


Clip = Annotated[StandInClip | SampleClip, Field(discriminator="type")]


class DisplayListing(ConfigModel):
    clips: dict[str, Clip]
    scenarios: dict[str, dict[Camera, str]]


class ShownClip(ConfigModel):
    """What the page needs: the tag, the caption and where to fetch the clip."""

    type: Literal["STAND-IN", "SAMPLE"]
    caption: str
    url: str


class DisplayClips(ConfigModel):
    clips: dict[str, ShownClip]
    scenarios: dict[str, dict[Camera, str]]
    """Only clips this machine has, as recorded; a scenario listed has no Thermal tab."""


def load_display(
    config_dir: Path, data_dir: Path
) -> tuple[DisplayClips, dict[str, Path]]:
    """The page's view of the clips and each clip's file. A clip missing on this machine, or
    not matching its recorded hash, is left out, and its tabs keep the simulated view."""
    listing_path = config_dir / DISPLAY_NAME
    if not listing_path.is_file():
        return DisplayClips(clips={}, scenarios={}), {}
    raw = yaml.safe_load(listing_path.read_text(encoding="utf-8"))
    listing = DisplayListing.model_validate(raw)
    files = {
        name: data_dir / clip.path
        for name, clip in listing.clips.items()
        if _as_recorded(data_dir / clip.path, clip.sha256)
    }
    shown = {
        name: ShownClip(
            type=clip.type, caption=clip.caption(), url=f"/api/display/clip/{name}"
        )
        for name, clip in listing.clips.items()
        if name in files
    }
    scenarios = {
        scenario: {camera: name for camera, name in tabs.items() if name in shown}
        for scenario, tabs in listing.scenarios.items()
    }
    return DisplayClips(clips=shown, scenarios=scenarios), files


def _as_recorded(path: Path, sha256: str) -> bool:
    if not path.is_file():
        return False
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
        log.warning("display clip %s does not match its recorded hash: not used", path)
        return False
    return True


def demo_profiles(
    profiles: Sequence[SiteProfile], demo: Sequence[DemoScenario]
) -> list[SiteProfile]:
    """Only the demo's scenarios, in its order and under its titles; no demo lists all.
    Hidden scenarios still exist and can still be run, from the command line or a replay."""
    if not demo:
        return list(profiles)
    order = {d.id: i for i, d in enumerate(demo)}
    titles = {d.id: d.title for d in demo}
    kept = []
    for profile in profiles:
        choices = sorted(
            (c for c in profile.scenarios if c.scenario_id in order),
            key=lambda c: order[c.scenario_id],
        )
        if choices:
            renamed = [
                ScenarioChoice(scenario_id=c.scenario_id, title=titles[c.scenario_id])
                for c in choices
            ]
            kept.append(profile.model_copy(update={"scenarios": renamed}))
    return sorted(kept, key=lambda p: order[p.scenarios[0].scenario_id])
