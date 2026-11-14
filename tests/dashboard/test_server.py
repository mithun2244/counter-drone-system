"""The dashboard server, through FastAPI's test client: a fast replay of the edge-state sample,
and a small run with the real evidence keeper for labels and exports."""

import asyncio
import hashlib
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cuas.bus import InProcessBus
from cuas.clock import SimClock
from cuas.config import SiteConfig, ZoneLabels
from cuas.dashboard.contract import ModelStatus, ModelStep, RunInfo, contract_schema
from cuas.dashboard.replay import ReplayLauncher
from cuas.dashboard.server import STATIC, Hub, Started, create_app
from cuas.evidence.handoff import HandoffPackage
from cuas.evidence.keeper import EvidenceKeeper, start_keeper
from cuas.evidence.store import EvidenceStore
from cuas.evidence.verify import verify_chain
from cuas.schemas import ThreatAssessment, Track
from cuas.schemas.topics import THREAT, TRACK

ROOT = Path(__file__).resolve().parents[2]
EDGE = ROOT / "docs" / "samples" / "edge_states.jsonl"
FAST = 2000.0  # simulated seconds per wall second, so a replay takes milliseconds
STADIUM = {"profile_id": "fictional-stadium", "scenario_id": "s2"}


@pytest.fixture
def client(site: SiteConfig, tmp_path: Path):
    launcher = ReplayLauncher(EDGE, site.simulation.tick_s, pace=FAST)
    with TestClient(
        create_app(Hub(launcher), app_dir=tmp_path / "no-app")
    ) as test_client:
        yield test_client


def until_ended(ws) -> list[dict]:
    received = []
    while True:
        message = ws.receive_json()
        received.append(message)
        if message["type"] == "run" and message["state"] == "ended":
            return received


def test_a_client_gets_hello_then_the_whole_run(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert (hello["type"], hello["run"], hello["frame"]) == ("hello", None, None)
        assert {p["profile_id"] for p in hello["profiles"]} == {
            "fictional-processing-plant",
            "fictional-stadium",
        }
        reply = client.post("/api/runs", json=STADIUM)
        assert reply.status_code == 200 and reply.json()["state"] == "running"
        received = until_ended(ws)
    kinds = [m["type"] for m in received]
    assert kinds[0] == "run" and kinds[-1] == "run"
    frames = [m for m in received if m["type"] == "frame"]
    assert [f["t"] for f in frames] == [10.0, 20.0, 30.0, 40.0]
    assert "evidence" in kinds


def test_a_late_client_is_told_the_run_and_the_latest_frame(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        client.post("/api/runs", json=STADIUM)
        until_ended(ws)
    with client.websocket_connect("/ws") as late:
        hello = late.receive_json()
    assert hello["run"]["state"] == "ended"
    assert hello["frame"]["t"] == 40.0


def test_one_run_at_a_time_and_only_runs_the_server_has(
    site: SiteConfig, tmp_path: Path
) -> None:
    slow = ReplayLauncher(EDGE, site.simulation.tick_s, pace=1.0)
    with TestClient(create_app(Hub(slow), app_dir=tmp_path)) as client:
        assert client.post("/api/runs", json=STADIUM).status_code == 200
        busy = client.post("/api/runs", json=STADIUM)
        assert busy.status_code == 409 and isinstance(busy.json()["detail"], str)
        paused = client.post("/api/run/control", json={"action": "pause"})
        assert paused.json()["state"] == "paused"
        faster = client.post("/api/run/control", json={"action": "speed", "speed": 5})
        assert faster.json()["speed"] == 5.0
    with TestClient(create_app(Hub(slow), app_dir=tmp_path)) as client:
        other = {"profile_id": "fictional-stadium", "scenario_id": "s3"}
        assert client.post("/api/runs", json=other).status_code == 404


def test_control_needs_a_run_and_a_good_body(client: TestClient) -> None:
    assert client.post("/api/run/control", json={"action": "pause"}).status_code == 409
    bad = client.post("/api/run/control", json={"action": "speed"})
    assert bad.status_code == 422 and isinstance(bad.json()["detail"], str)


def test_the_contract_is_served(client: TestClient) -> None:
    assert client.get("/api/contract").json() == contract_schema()


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_no_api_documentation_pages_they_load_from_a_cdn(
    client: TestClient, path: str
) -> None:
    assert client.get(path).status_code == 404


def test_mount_paths_reference_page_and_root(
    client: TestClient, tmp_path: Path, site
) -> None:
    assert client.get("/reference/").status_code == 200
    assert "reference.js" in client.get("/reference/").text
    root = client.get("/", follow_redirects=False)
    assert (root.status_code, root.headers["location"]) == (307, "/reference/")
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "index.html").write_text("<p>operator dashboard</p>", encoding="utf-8")
    launcher = ReplayLauncher(EDGE, site.simulation.tick_s, pace=FAST)
    with TestClient(create_app(Hub(launcher), app_dir=app_dir)) as with_app:
        assert "operator dashboard" in with_app.get("/").text
        assert with_app.get("/reference/").status_code == 200
        assert with_app.get("/api/profiles").status_code == 200


def test_clips_are_served_only_by_real_ids_from_this_run(
    site: SiteConfig, tmp_path: Path
) -> None:
    run_id = json.loads(EDGE.read_text(encoding="utf-8").splitlines()[1])["run_id"]
    sample = tmp_path / EDGE.name
    sample.write_text(EDGE.read_text(encoding="utf-8"), encoding="utf-8")
    station = tmp_path / run_id / "station_st1"
    station.mkdir(parents=True)
    (station / "abcdef0123456789.mp4").write_bytes(b"not really a video")
    (tmp_path / "secret.txt").write_text("keep out", encoding="utf-8")
    launcher = ReplayLauncher(sample, site.simulation.tick_s, pace=1.0)
    with TestClient(create_app(Hub(launcher), app_dir=tmp_path / "no-app")) as client:
        assert (
            client.get("/api/clips/st1/abcdef0123456789").status_code == 404
        )  # no run yet
        client.post("/api/runs", json=STADIUM)
        good = client.get("/api/clips/st1/abcdef0123456789")
        assert good.status_code == 200 and good.content == b"not really a video"
        assert good.headers["content-type"] == "video/mp4"
        (station / "1111222233334444.wav").write_bytes(b"not really a sound")
        sound = client.get("/api/clips/st1/1111222233334444")
        assert sound.status_code == 200 and sound.content == b"not really a sound"
        assert sound.headers["content-type"] == "audio/wav"
        assert client.get("/api/clips/st2/1111222233334444").status_code == 404
        for bad in [
            "st9/abcdef0123456789",
            "st1/abc",
            "st1/..%2Fsecret",
            "st1/ABCDEF0123456789",
        ]:
            assert client.get(f"/api/clips/{bad}").status_code == 404, bad


def test_served_files_load_nothing_from_outside() -> None:
    outside = re.compile(r"https?://", re.IGNORECASE)
    files = [p for p in STATIC.rglob("*") if p.is_file()]
    assert files
    for path in files:
        assert not outside.search(path.read_text(encoding="utf-8")), path


class EvidenceLauncher:
    """A run that raises one red alert, then ticks its clock for a while, with the real
    evidence keeper behind the evidence bus."""

    PACE = 2.0  # 0.1 s of wall time a tick: time enough to pause it first
    TICKS = 20

    def __init__(self, run: RunInfo, run_dir: Path) -> None:
        self._run, self._run_dir = run, run_dir

    def profiles(self) -> list:
        return []

    async def start(self, request, publish) -> Started:
        control, evidence = InProcessBus(), InProcessBus()
        keeper = EvidenceKeeper(EvidenceStore(self._run_dir), self._run.run_id, LABELS)
        keeping = start_keeper(keeper, control, evidence)
        clock = SimClock(0.2, pace=self.PACE)

        async def play() -> None:
            clock.start()
            await control.publish(TRACK, QUAD)
            await control.publish(THREAT, RAISED)
            for _ in range(self.TICKS):
                await clock.tick()
            await control.close()
            await keeping

        done = asyncio.create_task(play())
        return Started(self._run, clock, self.PACE, None, done, self._run_dir, evidence)


LABELS = ZoneLabels(critical="Pitch", important="Grounds", perimeter="Perimeter")
QUAD = Track(
    track_id="trk-1",
    t=0.0,
    position_enu_m=(-300.0, 100.0, 60.0),
    velocity_mps=(10.0, 0.0, 0.0),
    covariance=tuple(tuple(float(i == j) for j in range(6)) for i in range(6)),
    n_stations=3,
    status="confirmed",
)
RAISED = ThreatAssessment(
    track_id="trk-1",
    t=0.0,
    score=0.8,
    level="red",
    zone="critical",
    time_to_impact_s=20.0,
    reasons=("heading to Pitch, 20 s",),
    alert_id="alert-1",
)


def next_evidence(ws) -> dict:
    while (message := ws.receive_json())["type"] != "evidence":
        pass
    return message


def test_labels_and_exports_go_through_the_evidence_keeper(tmp_path: Path) -> None:
    run = RunInfo.model_validate_json(EDGE.read_text(encoding="utf-8").splitlines()[1])
    run_dir = tmp_path / "run"
    hub = Hub(EvidenceLauncher(run, run_dir))
    with (
        TestClient(create_app(hub, app_dir=tmp_path / "no-app")) as client,
        client.websocket_connect("/ws") as ws,
    ):
        ws.receive_json()
        client.post("/api/runs", json=STADIUM)
        client.post("/api/run/control", json={"action": "pause"})
        assert next_evidence(ws)["kind"] == "alert"
        label = client.post("/api/alerts/alert-1/label", json={"label": "confirm"})
        assert label.status_code == 200 and label.json()["seq"] == 2
        event = next_evidence(ws)
        assert (
            0.0 <= event.pop("t") <= 0.2 * EvidenceLauncher.TICKS
        )  # the time it was paused
        assert event == {
            "contract": 1,
            "type": "evidence",
            "run_id": run.run_id,
            "seq": 2,
            "kind": "label",
            "alert_id": "alert-1",
            "record_hash": label.json()["record_hash"],
        }
        unknown = client.post("/api/alerts/alert-9/label", json={"label": "confirm"})
        assert unknown.status_code == 404 and isinstance(unknown.json()["detail"], str)
        bad = client.post("/api/alerts/alert-1/label", json={"label": "maybe"})
        assert bad.status_code == 422
        export = client.post("/api/alerts/alert-1/export").json()
        package = HandoffPackage.model_validate(export["package"])
        assert (
            package.labels[0].label == "confirm" and package.alert.alert_id == "alert-1"
        )
        stored = (run_dir / export["path"]).read_bytes()
        assert export["sha256"] == hashlib.sha256(stored).hexdigest()
        client.post("/api/run/control", json={"action": "play"})
        received = until_ended(ws)
        late = client.post("/api/alerts/alert-1/label", json={"label": "dismiss"})
        assert late.status_code == 409
    kinds = [m["kind"] for m in received if m["type"] == "evidence"]
    assert kinds == ["export", "export"]  # the operator's, then the one at run end
    assert verify_chain(run_dir).problems == []


def test_a_replay_keeps_no_evidence_so_labels_are_refused(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        client.post("/api/runs", json=STADIUM)
        reply = client.post("/api/alerts/alert-1/label", json={"label": "confirm"})
        assert reply.status_code == 409
        until_ended(ws)


def test_the_reference_page_labels_recorded_audio_as_the_clean_source() -> None:
    """The classifier heard a noise-mixed version: the page must not suggest otherwise."""
    page = (STATIC / "reference" / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "reference" / "reference.js").read_text(encoding="utf-8")
    assert "Recorded audio" in page and "Clean source audio" in page
    assert "card.sounds" in script


def test_root_serves_the_operator_dashboard_and_its_files(site: SiteConfig) -> None:
    launcher = ReplayLauncher(EDGE, site.simulation.tick_s, pace=FAST)
    with TestClient(create_app(Hub(launcher))) as client:  # the real static/app
        root = client.get("/", follow_redirects=False)
        assert root.status_code == 200
        for name in ("app.css", "text.js", "map.js", "simview.js", "app.js"):
            assert name in root.text
            assert client.get(f"/{name}").status_code == 200, name
        assert client.get("/reference/").status_code == 200


def test_the_operator_dashboard_shows_the_required_wording() -> None:
    """Contract and design wording: clean-source audio, the export label, B4 states, and the
    simulated-scenario notice with the basemap's own notice and attribution."""
    app = STATIC / "app"
    page = (app / "index.html").read_text(encoding="utf-8")
    text = (app / "text.js").read_text(encoding="utf-8")
    script = (app / "map.js").read_text(encoding="utf-8")
    # classic scripts, not modules: some Windows setups serve .js as text/plain
    assert '<script src="text.js"></script>' in page
    assert "Clean source audio" in text and "Recorded audio" in text
    assert '"Export hand-off JSON"' in text
    assert "All clear · last check" in text
    assert "Engine heard, {compass}, unconfirmed" in text
    assert "Simulated scenario: fictional site · local grid {grid} m" in text
    assert "basemap.notice" in script and "basemap.attribution" in script


def test_the_operator_dashboard_layout_and_selected_track_details() -> None:
    """Three columns with the video over the map and audio in the selected alert's evidence
    panel; track details say so in words when a value is unavailable."""
    app = STATIC / "app"
    page = (app / "index.html").read_text(encoding="utf-8")
    text = (app / "text.js").read_text(encoding="utf-8")
    assert (
        page.index('id="status-panel"')
        < page.index('id="map-panel"')
        < page.index('id="side"')
    )
    overlay = page[page.index('id="map-panel"') : page.index('id="side"')]
    assert (
        'id="video-overlay"' in overlay
        and 'id="clip"' in overlay
        and 'id="collapse"' in overlay
    )
    details = page[page.index('id="details-panel"') :]
    assert (
        'id="sounds"' in details
        and 'id="audio"' in details
        and 'id="evidence"' in details
    )
    assert 'id="clip-panel"' not in page
    assert "unavailable: track {id} not in this frame" in text
    assert "unavailable: near-stationary" in text
    assert "metres from the site origin" in text and "clockwise from north" in text
    assert 'course: "Direction of travel"' in text


def test_the_operator_dashboard_draws_labelled_acoustic_sectors() -> None:
    """pre_alerts as wedges behind their own toggle, on by default, labelled with sensor and
    heard-from direction, listed under System status; grid beyond the basemap is labelled."""
    app = STATIC / "app"
    page = (app / "index.html").read_text(encoding="utf-8")
    text = (app / "text.js").read_text(encoding="utf-8")
    assert '<input type="checkbox" id="sectors" checked>' in page
    assert '<input type="checkbox" id="rays">' in page
    status = page[page.index('id="status-panel"') : page.index('id="map-panel"')]
    assert 'id="acoustic"' in status
    assert '"Acoustic sectors"' in text and '"Acoustic detections"' in text
    assert "{sensor} · Engine heard {direction} · Unconfirmed" in text
    assert "Outside basemap coverage" in text
    assert "Last heard from {sensor} · {direction} · {t}" in text
    assert (
        "{sensor} · heard {direction} · Acoustic warning · Camera unconfirmed" in text
    )
    assert "Acoustic warning, {direction}, camera unconfirmed" in text
    assert "no camera recording was matched to this track" in text


def test_stop_ends_the_run_and_leaves_the_server_ready(
    site: SiteConfig, tmp_path: Path
) -> None:
    slow = ReplayLauncher(EDGE, site.simulation.tick_s, pace=1.0)  # 40 s at real time
    with (
        TestClient(create_app(Hub(slow), app_dir=tmp_path)) as client,
        client.websocket_connect("/ws") as ws,
    ):
        ws.receive_json()
        assert client.post("/api/run/stop").status_code == 409  # nothing to stop yet
        client.post("/api/runs", json=STADIUM)
        client.post("/api/run/control", json={"action": "pause"})
        stopped = client.post("/api/run/stop")
        assert stopped.status_code == 200
        assert (stopped.json()["state"], stopped.json()["ended_reason"]) == (
            "ended",
            "stopped",
        )
        ended = until_ended(ws)[-1]
        assert ended["ended_reason"] == "stopped"
        assert client.post("/api/run/stop").status_code == 409
        again = client.post("/api/runs", json=STADIUM)
        assert again.status_code == 200 and again.json()["state"] == "running"


def test_a_run_that_finishes_or_fails_says_so(site: SiteConfig, tmp_path: Path) -> None:
    fast = ReplayLauncher(EDGE, site.simulation.tick_s, pace=FAST)
    with (
        TestClient(create_app(Hub(fast), app_dir=tmp_path)) as client,
        client.websocket_connect("/ws") as ws,
    ):
        ws.receive_json()
        client.post("/api/runs", json=STADIUM)
        assert until_ended(ws)[-1]["ended_reason"] == "completed"
    run = RunInfo.model_validate_json(EDGE.read_text(encoding="utf-8").splitlines()[1])
    with (
        TestClient(create_app(Hub(FailingLauncher(run)), app_dir=tmp_path)) as client,
        client.websocket_connect("/ws") as ws,
    ):
        ws.receive_json()
        client.post("/api/runs", json=STADIUM)
        assert until_ended(ws)[-1]["ended_reason"] == "failed"


class FailingLauncher:
    """A run whose task raises, as a crash in the simulator or pipeline would."""

    def __init__(self, run: RunInfo) -> None:
        self._run = run

    def profiles(self) -> list:
        return []

    async def start(self, request, publish) -> Started:
        async def crash() -> None:
            await asyncio.sleep(0.01)
            raise RuntimeError("a deliberate failure")

        clock = SimClock(0.2, pace=1.0)
        return Started(self._run, clock, 1.0, None, asyncio.create_task(crash()))


def test_the_operator_dashboard_has_a_stop_with_its_own_confirm() -> None:
    app = STATIC / "app"
    page = (app / "index.html").read_text(encoding="utf-8")
    script = (app / "app.js").read_text(encoding="utf-8")
    assert 'id="stop"' in page and 'id="stop-confirm"' in page
    assert '"/api/run/stop"' in script
    assert "confirm(" not in script.replace("stop-confirm", "")  # no browser dialog


def test_recorded_media_waits_for_the_models_and_simulator_runs_do_not(
    site: SiteConfig, tmp_path: Path
) -> None:
    hub = Hub(ReplayLauncher(EDGE, site.simulation.tick_s, pace=FAST))
    media = {**STADIUM, "recorded_media": True}
    with (
        TestClient(create_app(hub, app_dir=tmp_path)) as client,
        client.websocket_connect("/ws") as ws,
    ):
        assert ws.receive_json()["models"] is None  # a replay loads no models
        steps = [
            ModelStep(name="RGB detector", state="ready"),
            ModelStep(name="Thermal detector", state="loading"),
        ]
        hub.publish(ModelStatus(state="loading", steps=steps))
        assert ws.receive_json()["type"] == "models"
        loading = client.post("/api/runs", json=media)
        assert (
            loading.status_code == 409 and "still loading" in loading.json()["detail"]
        )
        steps[1] = ModelStep(
            name="Thermal detector", state="failed", detail="RuntimeError: bad file"
        )
        hub.publish(ModelStatus(state="failed", steps=steps))
        failed = client.post("/api/runs", json=media)
        assert failed.status_code == 409
        assert "Thermal detector: RuntimeError: bad file" in failed.json()["detail"]
        assert client.post("/api/runs", json=STADIUM).status_code == 200
    with (
        TestClient(create_app(hub, app_dir=tmp_path)) as client,
        client.websocket_connect("/ws") as late,
    ):
        assert late.receive_json()["models"]["state"] == "failed"


def test_the_operator_dashboard_shows_model_loading() -> None:
    app = STATIC / "app"
    text = (app / "text.js").read_text(encoding="utf-8")
    script = (app / "app.js").read_text(encoding="utf-8")
    assert "Loading models… {done} of {total} ({step})" in text
    assert "Simulator runs still work." in text
    assert 'message.type === "models"' in script
    assert '$("go").disabled' in script and '$("media").disabled' in script


def test_clip_captions_say_they_are_dataset_samples_not_this_track() -> None:
    app = STATIC / "app"
    text = (app / "text.js").read_text(encoding="utf-8")
    script = (app / "app.js").read_text(encoding="utf-8")
    assert "Sample clip from {dataset} - not footage of this track" in text
    assert 'zoom: "Zoom (stand-in clip)"' in text
    assert "Sample recording from {dataset}" in text
    assert "{source} at {at} s" not in text
    assert "look.dataset" in script and "s.dataset" in script


def test_simulated_values_are_tagged_capped_and_inside_zone_replaces_tti() -> None:
    app = STATIC / "app"
    page = (app / "index.html").read_text(encoding="utf-8")
    text = (app / "text.js").read_text(encoding="utf-8")
    script = (app / "app.js").read_text(encoding="utf-8")
    assert 'class="note legend"' in page and 'data-text="simLegend"' in page
    assert "not measured on a real sensor" in text and 'sim: "SIM"' in text
    assert "const MAX_SHOWN_PCT = 99;" in script
    assert "Math.round(100 * a.confidence)" not in script  # every % goes through pct()
    assert "Math.round(100 * card.confidence)" not in script
    assert 'insideZone: "INSIDE ZONE"' in text and 'a.approach === "inside"' in script
    assert script.count("simTag()") >= 4  # card, summary, sensor rows, faults line


def test_a_request_the_keeper_cannot_answer_times_out_and_the_next_one_works(
    tmp_path: Path, monkeypatch
) -> None:
    run = RunInfo.model_validate_json(EDGE.read_text(encoding="utf-8").splitlines()[1])
    hub = Hub(EvidenceLauncher(run, tmp_path / "run"), request_timeout_s=0.5)
    real_handle = EvidenceKeeper.handle

    def broken_once(keeper, request):
        monkeypatch.setattr(EvidenceKeeper, "handle", real_handle)
        raise OSError("disk full")

    with (
        TestClient(create_app(hub, app_dir=tmp_path / "no-app")) as client,
        client.websocket_connect("/ws") as ws,
    ):
        ws.receive_json()
        client.post("/api/runs", json=STADIUM)
        client.post("/api/run/control", json={"action": "pause"})
        assert next_evidence(ws)["kind"] == "alert"
        monkeypatch.setattr(EvidenceKeeper, "handle", broken_once)
        lost = client.post("/api/alerts/alert-1/label", json={"label": "confirm"})
        assert (
            lost.status_code == 504
            and "did not answer in 0.5 s" in lost.json()["detail"]
        )
        again = client.post("/api/alerts/alert-1/label", json={"label": "confirm"})
        assert again.status_code == 200 and again.json()["seq"] == 2
        client.post("/api/run/stop")


def test_acoustic_panel_lists_linked_events_and_zero_records_say_why() -> None:
    """The panel lists what the wedges and alert reasons use, so it never says None while an
    alert says "engine heard"; a card never shows a bare "0 evidence records"."""
    app = STATIC / "app"
    text = (app / "text.js").read_text(encoding="utf-8")
    script = (app / "app.js").read_text(encoding="utf-8")
    acoustic = script[script.index("function renderAcoustic") :]
    acoustic = acoustic[: acoustic.index("function recordsText")]
    assert "pre_alerts" in acoustic and "tr.heard" in acoustic
    assert 'a.reasons.includes("engine heard")' in acoustic
    assert "microphone or picket sound linked to {track}" in text
    assert "Evidence record being written…" in text
    assert "No evidence kept: replayed stream" in text
    assert script.count("recordsText(") == 3  # defined once, used on cards and details


def test_big_drone_video_panel_wording_and_simulated_view() -> None:
    """S1's sequence: acoustic only, then a SIMULATED camera view, never presented as footage;
    auto-open never changes the operator's selection."""
    app = STATIC / "app"
    page = (app / "index.html").read_text(encoding="utf-8")
    text = (app / "text.js").read_text(encoding="utf-8")
    script = (app / "app.js").read_text(encoding="utf-8")
    view = (app / "simview.js").read_text(encoding="utf-8")
    assert '<canvas id="simview"></canvas>' in page
    assert '<script src="simview.js"></script>' in page
    assert "Acoustic detection only - camera cued to bearing {deg}°, searching" in text
    assert "Camera detection at {t} by {station}" in text
    assert 'simLabel: "SIMULATED CAMERA VIEW - not real footage"' in text
    assert 'cameraDetected: "Camera detected"' in text
    assert 't("simLabel")' in view and "drawCrosshair" in view
    pick = script[script.index("function pickCue") : script.index("function showBadge")]
    assert "state.selected =" not in pick  # picking a cue never selects an alert
    assert 'cue.views.find((v) => v.camera === "zoom")' in script  # zoom once assigned
