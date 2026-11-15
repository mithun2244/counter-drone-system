"""The Zoom tab's stand-in clip: real fixed-wing footage, captioned from its listing, never
presented as footage of the track and never given a detection box."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from cuas.config import SiteConfig
from cuas.dashboard.replay import ReplayLauncher
from cuas.dashboard.server import STATIC, Hub, create_app
from cuas.dashboard.standin import STANDIN_NAME, load_standin

ROOT = Path(__file__).resolve().parents[2]
EDGE = ROOT / "docs" / "samples" / "edge_states.jsonl"
APP = STATIC / "app"
CLIP = b"not really a video"


def _listing(tmp_path: Path, sha256: str) -> tuple[Path, Path]:
    """The committed listing, pointed at a small file of our own."""
    config, data = tmp_path / "config", tmp_path / "data"
    (data / "standin").mkdir(parents=True)
    config.mkdir()
    raw = yaml.safe_load((ROOT / "config" / STANDIN_NAME).read_text(encoding="utf-8"))
    raw["standin"] |= {"path": "standin/clip.mp4", "sha256": sha256}
    (config / STANDIN_NAME).write_text(yaml.safe_dump(raw), encoding="utf-8")
    return config, data


def test_committed_listing_names_its_source_licence_and_type() -> None:
    raw = yaml.safe_load((ROOT / "config" / STANDIN_NAME).read_text(encoding="utf-8"))
    entry = raw["standin"]
    assert entry["type"] == "STAND-IN"
    assert entry["licence"] == "public domain"
    assert entry["source_url"].startswith("https://www.dvidshub.net/video/493473/")
    assert entry["author"] and entry["downloaded"] and len(entry["sha256"]) == 64


def test_clip_is_used_only_when_present_and_as_recorded(tmp_path: Path) -> None:
    config, data = _listing(tmp_path, hashlib.sha256(CLIP).hexdigest())
    assert load_standin(config, data) is None  # no file on this machine
    (data / "standin" / "clip.mp4").write_bytes(CLIP)
    loaded = load_standin(config, data)
    assert loaded is not None and loaded[0].title == "RQ-7B Shadow fixed-wing drone"
    (data / "standin" / "clip.mp4").write_bytes(CLIP + b"!")
    assert load_standin(config, data) is None  # another file under the same name
    assert load_standin(tmp_path / "nowhere", data) is None


def test_server_serves_the_clip_and_its_listing_or_404(
    site: SiteConfig, tmp_path: Path
) -> None:
    config, data = _listing(tmp_path, hashlib.sha256(CLIP).hexdigest())
    (data / "standin" / "clip.mp4").write_bytes(CLIP)
    launcher = ReplayLauncher(EDGE, site.simulation.tick_s, pace=0.0)
    app = create_app(
        Hub(launcher), app_dir=tmp_path, standin=load_standin(config, data)
    )
    with TestClient(app) as client:
        listing = client.get("/api/standin").json()
        assert listing["type"] == "STAND-IN" and listing["source"] == "DVIDS"
        clip = client.get("/api/standin/clip")
        assert clip.content == CLIP and clip.headers["content-type"] == "video/mp4"
    with TestClient(create_app(Hub(launcher), app_dir=tmp_path)) as client:
        assert client.get("/api/standin").status_code == 404
        assert client.get("/api/standin/clip").status_code == 404


def test_page_wording_tag_and_no_box_on_the_stand_in_clip() -> None:
    page = (APP / "index.html").read_text(encoding="utf-8")
    text = (APP / "text.js").read_text(encoding="utf-8")
    script = (APP / "app.js").read_text(encoding="utf-8")
    assert (
        '"Stand-in clip: {title} - {source}, {author}, {licence} - not footage of this track"'
        in text
    )
    assert 'standinTag: "STAND-IN"' in text
    assert (
        '<video id="standin" muted loop playsinline></video>' in page
    )  # no audio, loops
    assert 'data-text="standinTag"' in page
    # Zoom tab only, only while the zoom is on the target; otherwise the simulated view.
    assert (
        'view.camera === "zoom" && state.standin && !simTargetOutside(view)' in script
    )
    assert "if (view && !standin && !state.collapsed) drawSimView" in script
    # The clip is a plain <video>: nothing is ever drawn over it.
    assert "getContext" not in script[script.index("async function loadStandin") :]


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
