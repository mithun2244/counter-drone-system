"""The dashboard server, through FastAPI's test client and a fast replay of the edge-state sample."""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cuas.config import SiteConfig
from cuas.dashboard.contract import contract_schema
from cuas.dashboard.replay import ReplayLauncher
from cuas.dashboard.server import STATIC, Hub, create_app

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
