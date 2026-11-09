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
from cuas.dashboard.contract import RunInfo, contract_schema
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
