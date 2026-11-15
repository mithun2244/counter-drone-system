"""Real video for the camera tabs, the demo's two scenarios, and pages that never go stale."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from cuas.config import DemoScenario, SiteConfig
from cuas.dashboard.contract import ScenarioChoice, SiteProfile
from cuas.dashboard.display import DISPLAY_NAME, demo_profiles, load_display
from cuas.dashboard.replay import ReplayLauncher
from cuas.dashboard.server import STATIC, Hub, create_app
from cuas.media_manifest import load_manifest

ROOT = Path(__file__).resolve().parents[2]
EDGE = ROOT / "docs" / "samples" / "edge_states.jsonl"
APP = STATIC / "app"
CLIP = b"not really a video"
STAND_IN = {
    "type": "STAND-IN", "title": "Some drone", "source": "DVIDS", "author": "A. Author",
    "licence": "public domain", "source_title": "T", "source_url": "https://www.dvidshub.net/video/1/x",
    "downloaded": "2026-11-15", "edits": "none", "path": "standin/a.mp4",
}  # fmt: skip
SAMPLE = {
    "type": "SAMPLE", "dataset": "Svanström Drone Detection Dataset", "source_title": "V_DRONE_1",
    "path": "svanstrom/b.mp4",
}  # fmt: skip


def _committed() -> dict:
    return yaml.safe_load((ROOT / "config" / DISPLAY_NAME).read_text(encoding="utf-8"))


def _setup(tmp_path: Path, files: dict[str, bytes]) -> tuple[Path, Path]:
    """A listing with one clip of each type, and the files given (by clip path)."""
    config, data = tmp_path / "config", tmp_path / "data"
    config.mkdir()
    for path, content in files.items():
        (data / path).parent.mkdir(parents=True, exist_ok=True)
        (data / path).write_bytes(content)
    sha = hashlib.sha256(CLIP).hexdigest()
    listing = {
        "clips": {"far": STAND_IN | {"sha256": sha}, "near": SAMPLE | {"sha256": sha}},
        "scenarios": {"s1": {"wide": "far", "zoom": ["near", "far"]}},
        "zoom_only": ["s1"],
    }
    (config / DISPLAY_NAME).write_text(yaml.safe_dump(listing), encoding="utf-8")
    return config, data


def test_committed_clips_are_honestly_sourced_and_mapped() -> None:
    listing = _committed()
    manifest = {c.path: c for c in load_manifest(ROOT / "config").clips}
    for clip in listing["clips"].values():
        if clip["type"] == "STAND-IN":
            assert clip["licence"] == "public domain"
            assert clip["source_url"].startswith("https://www.dvidshub.net/video/")
        else:  # a held-out dataset clip: the same file the manifest records, never trained on
            assert manifest[clip["path"]].sha256 == clip["sha256"]
            assert manifest[clip["path"]].split == "test"
            assert manifest[clip["path"]].label == "drone"
    for tabs in listing["scenarios"].values():
        assert set(tabs) <= {"wide", "zoom"}
        for names in tabs.values():
            names = [names] if isinstance(names, str) else names
            assert all(name in listing["clips"] for name in names)
            assert (
                len({listing["clips"][n]["type"] for n in names}) == 1
            )  # one tag per tab


def test_captions_and_urls(tmp_path: Path) -> None:
    config, data = _setup(tmp_path, {"standin/a.mp4": CLIP, "svanstrom/b.mp4": CLIP})
    shown, files = load_display(config, data)
    assert shown.clips["far"].caption == (
        "Stand-in clip: Some drone - DVIDS, A. Author, public domain - not footage of this track"
    )
    assert shown.clips["near"].caption == (
        "Sample clip from Svanström Drone Detection Dataset - not footage of this track"
    )
    assert shown.clips["near"].type == "SAMPLE"
    assert shown.clips["far"].url == "/api/display/clip/far"
    assert shown.scenarios == {"s1": {"wide": ["far"], "zoom": ["near", "far"]}}
    assert shown.zoom_only == ("s1",)
    assert files["near"] == data / "svanstrom" / "b.mp4"


def test_missing_or_changed_clip_leaves_its_tab_simulated(tmp_path: Path) -> None:
    config, data = _setup(
        tmp_path, {"standin/a.mp4": CLIP + b"!"}
    )  # changed; near missing
    shown, files = load_display(config, data)
    assert shown.clips == {} and files == {}
    assert shown.scenarios == {"s1": {}}
    assert load_display(tmp_path / "nowhere", data)[0].clips == {}


def test_server_serves_clips_and_never_lets_a_page_go_stale(
    site: SiteConfig, tmp_path: Path
) -> None:
    config, data = _setup(tmp_path, {"standin/a.mp4": CLIP, "svanstrom/b.mp4": CLIP})
    launcher = ReplayLauncher(EDGE, site.simulation.tick_s, pace=0.0)
    app = create_app(Hub(launcher), display=load_display(config, data))
    with TestClient(app) as client:
        listing = client.get("/api/display").json()
        assert listing["scenarios"]["s1"] == {"wide": ["far"], "zoom": ["near", "far"]}
        assert listing["zoom_only"] == ["s1"]
        clip = client.get("/api/display/clip/far")
        assert clip.content == CLIP and clip.headers["content-type"] == "video/mp4"
        assert client.get("/api/display/clip/nothing").status_code == 404
        for path in ("/", "/app.js", "/text.js", "/app.css", "/api/display"):
            assert client.get(path).headers["cache-control"] == "no-cache", path
    with TestClient(create_app(Hub(launcher), app_dir=tmp_path)) as client:
        assert client.get("/api/display").json() == {
            "clips": {},
            "scenarios": {},
            "zoom_only": [],
        }


def _profile(pid: str, *ids: str) -> SiteProfile:
    return SiteProfile(
        profile_id=pid,
        venue=pid,
        zone_labels={},
        scenarios=[ScenarioChoice(scenario_id=i, title=i.upper()) for i in ids],
    )


def test_demo_lists_only_its_scenarios_in_order_under_its_titles() -> None:
    profiles = [_profile("stadium", "s2", "s3", "s4"), _profile("plant", "s1", "s5")]
    demo = (DemoScenario(id="s1", title="Large"), DemoScenario(id="s2", title="Small"))
    shown = demo_profiles(profiles, demo)
    assert [p.profile_id for p in shown] == ["plant", "stadium"]
    assert [(c.scenario_id, c.title) for p in shown for c in p.scenarios] == [
        ("s1", "Large"),
        ("s2", "Small"),
    ]
    assert demo_profiles(profiles, ()) == profiles  # nothing hidden without a demo list


def test_site_demo_is_s1_then_s2_and_the_rest_stay(site: SiteConfig) -> None:
    demo = site.dashboard.demo_scenarios
    assert [(d.id, d.title) for d in demo] == [
        ("s1", "Large attack drone - processing plant"),
        ("s2", "Small drone - stadium"),
    ]
    zoom_only = _committed()["zoom_only"]
    assert set(zoom_only) == {"s1", "s2"}  # Option B in both demo scenarios
    assert all(
        set(_committed()["scenarios"][s]) == {"zoom"} for s in zoom_only
    )  # no Wide tab
    for hidden in ("s3", "s4", "s5"):  # hidden, not removed
        assert any((ROOT / "config" / "scenarios").glob(f"{hidden}_*.yaml"))


def test_page_wording_tags_and_tabs() -> None:
    page = (APP / "index.html").read_text(encoding="utf-8")
    text = (APP / "text.js").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    assert "standinTag" not in page + text + script  # the stray literal is gone
    assert '<span id="standin-tag" class="clip-tag"></span>' in page
    assert '<span id="clip-tag" class="clip-tag" hidden></span>' in page
    assert '<video id="standin" muted playsinline></video>' in page  # no audio
    assert (
        '<video id="standin-b" muted playsinline></video>' in page
    )  # for the crossfade
    assert 'displayWideTab: "{station} Wide RGB ({kind})"' in text
    assert 'displayZoomTab: "{station} Zoom ({kind})"' in text
    assert '$("standin-tag").textContent = clip.type;' in script
    assert '$("clip-tag").textContent = clip ? clip.type : "SAMPLE";' in script
    # A scenario with display clips has no Thermal tab; the simulated view only without a clip.
    assert 'looks.filter((l) => !l.source.endsWith(".thermal"))' in script
    assert "if (view && !clip && !state.collapsed) drawSimView" in script
    # Option B: no video before a zoom camera is on the track, then only the Zoom tab.
    assert 'zoomTab: "ZOOM camera ({kind})"' in text
    assert (
        'wideSlewing: "Wide camera detection at {t} by {station} - zoom slewing to target"'
        in text
    )
    assert '$("looks").replaceChildren(...(zoom ? [tab] : []));' in script
    assert 'overlay.classList.toggle("viewing", Boolean(zoom));' in script
    zoom_only = script[
        script.index("function zoomSubject") : script.index("function zoomOnTrack")
    ]
    assert (
        "state.selected =" not in zoom_only
    )  # opening by itself never selects an alert
    # Nothing is ever drawn over a clip: both are plain <video> elements.
    assert "getContext" not in script


@pytest.mark.parametrize(
    ("off_az", "off_el", "outside"),
    [(0.0, 0.0, False), (0.9, 0.5, False), (1.1, 0.0, True), (0.0, 0.7, True), (-6.12, -3.74, True)],
)  # fmt: skip
def test_target_outside_the_zoom_field_of_view(
    off_az: float, off_el: float, outside: bool
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    view = {
        "fov_deg": 2.0, "pointing_azimuth_deg": 359.5, "pointing_elevation_deg": 5.0,
        "seen_azimuth_deg": (359.5 + off_az) % 360, "seen_elevation_deg": 5.0 + off_el,
    }  # fmt: skip
    harness = (
        'const fs = require("fs");'
        'console.log(new Function("view", fs.readFileSync(process.argv[2], "utf8")'
        ' + "; return simTargetOutside(view);")(JSON.parse(process.argv[3])));'
    )
    out = subprocess.run(
        [node, "-", str(APP / "simview.js"), json.dumps(view)],
        input=harness, capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert out.stdout.strip() == str(outside).lower()
