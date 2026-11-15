"""Fresh display observations and the operator camera state machine."""

import shutil
import subprocess
from pathlib import Path

import pytest

from cuas.dashboard.cues import CueTracker
from cuas.geometry import bearing_to
from cuas.schemas import BearingDetection
from tests.dashboard.test_cues import confirmed


def test_rgb_requires_fresh_unique_track_link(site):
    cues = CueTracker(site)
    track = confirmed(10, (100, 500, 80))
    az, el, _ = bearing_to(site.stations[0].position_enu_m, track.position_enu_m)
    ray = BearingDetection(
        station_id=site.stations[0].id,
        sensor="rgb",
        t=10,
        azimuth_deg=az,
        elevation_deg=el,
        sigma_deg=0.1,
    )
    tracks = {track.track_id: track}
    cues.ingest(ray.model_copy(update={"sensor": "thermal"}))
    assert cues.current_rgb(track.track_id, tracks, 10) is None
    cues.ingest(ray)
    assert cues.current_rgb(track.track_id, tracks, 10) == 10
    assert cues.current_rgb(track.track_id, tracks, 12) is None
    assert cues.current_rgb("another", tracks, 10) is None
    other = track.model_copy(update={"track_id": "another"})
    assert cues.current_rgb(track.track_id, {**tracks, "another": other}, 10) is None
    assert cues.current_rgb(track.track_id, tracks, 9) is None


def test_controlled_zoom_rgb_zoom_and_selection_reset():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for dashboard JavaScript regression")
    app = Path("src/cuas/dashboard/static/app/app.js").read_text(encoding="utf-8")
    helper = app[app.index("const handoff =") : app.index("function renderZoomOnly()")]
    script = (
        helper
        + """
const assert = require('node:assert/strict');
assert.equal(cameraHandoff('run:a', false, true), 'opening');
assert.equal(cameraHandoff('run:a', true, true), 'zoom');
assert.equal(cameraHandoff('run:a', false, true), 'wide');
assert.equal(cameraHandoff('run:a', false, true), 'wide');
assert.equal(cameraHandoff('run:a', false, false), 'out');
assert.equal(cameraHandoff('run:a', true, false), 'zoom');
assert.equal(cameraHandoff('run:b', false, true), 'opening');
assert.equal(cameraHandoff('run2:a', false, true), 'opening');
"""
    )
    subprocess.run([node, "-e", script], check=True)


def test_clip_updates_do_not_reload_playback():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    app = Path("src/cuas/dashboard/static/app/app.js").read_text(encoding="utf-8")
    helper = app[app.index("function showParts(") : app.index("function loadPart(")]
    script = (
        """
const assert = require('node:assert/strict');
const state = {collapsed:false};
const nodes = new Map();
const $ = id => {if (!nodes.has(id)) nodes.set(id, {classList:{toggle() {}}}); return nodes.get(id);};
let loads = 0;
const player = {key:'', front:{play:()=>Promise.resolve()}};
const startParts = (parts,key) => {loads++; player.key=key;};
const pauseParts = () => {};
const renderSampleEnd = () => {};
"""
        + helper
        + """
const zoom = {type:'STAND-IN',caption:'DVIDS',parts:[{url:'/local/zoom'}]};
const wide = {type:'STAND-IN',caption:'DVIDS',parts:[{url:'/local/wide'}]};
showParts(zoom,false); showParts(zoom,false); assert.equal(loads,1);
showParts(wide,false); showParts(wide,false); assert.equal(loads,2);
showParts(zoom,false); assert.equal(loads,3);
assert.equal($('standin-tag').textContent,'STAND-IN');
assert.equal($('standin-note').textContent,'DVIDS');
"""
    )
    subprocess.run([node, "-e", script], check=True)


def test_s2_player_and_wedges():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    subprocess.run([node, "tests/dashboard/s2_player.cjs"], check=True)
