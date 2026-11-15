"""Live dashboard runs from the composition root (scripts/live_runs.py)."""

import asyncio
import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

from cuas.clock import SimClock
from cuas.config import SiteConfig, ZoneLabels
from cuas.dashboard.contract import EvidenceHead, Frame, ModelStatus, StartRun
from cuas.dashboard.frames import FrameBuilder
from cuas.dashboard.server import Hub, create_app
from cuas.evidence.verify import verify_chain
from cuas.schemas import OperatorLabel
from cuas.schemas.topics import EVIDENCE_RECORD, OPERATOR_LABEL

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "live_runs.py"
FAST = 2000.0  # simulated seconds per wall second: as fast as the run computes
S2_SEED_7 = StartRun(profile_id="fictional-stadium", scenario_id="s2", seed=7)


@pytest.fixture
def live() -> ModuleType:
    spec = importlib.util.spec_from_file_location("live_runs", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def launcher(live: ModuleType, runs_dir: Path, models_dir: Path = ROOT / "models"):
    return live.LiveLauncher(
        ROOT / "config", ROOT / "data", models_dir, runs_dir, pace=FAST
    )


async def test_a_live_run_streams_every_frame_and_changes_no_control_output(
    live: ModuleType, tmp_path: Path, site: SiteConfig, record_pipeline, capsys
) -> None:
    (tmp_path / "s2_seed7_001").mkdir()  # an earlier run's folder is never reused
    published: list = []
    started = await launcher(live, tmp_path).start(S2_SEED_7, published.append)
    assert started.evidence is not None
    records = started.evidence.subscribe(EVIDENCE_RECORD)
    raised = await anext(records)
    label = OperatorLabel(
        alert_id=raised.alert_id, label="confirm", t=raised.t, request_id="req-1"
    )
    await started.evidence.publish(OPERATOR_LABEL, label)
    answers = [r async for r in records if r.request_id == "req-1"]
    await started.done
    assert (raised.kind, [a.kind for a in answers]) == ("alert", ["label"])
    assert started.run.run_id == "s2_seed7_002"
    assert (tmp_path / "s2_seed7_002").is_dir() and started.clips_dir is None
    frames = [m for m in published if isinstance(m, Frame)]
    period = site.dashboard.frame_period_s
    times = [f.t for f in frames]
    marks = sorted(set(times))
    assert times == sorted(times) and marks == [k * period for k in range(len(marks))]
    assert len(times) > len(marks)  # evidence records sent the latest frame again
    assert frames[-1].t >= started.run.duration_s
    assert any(f.alerts for f in frames)
    _, _, controlled, _ = await record_pipeline("s2", seed=7)
    printed = capsys.readouterr().out
    assert f"control digest sha256:{live.digest(controlled)}" in printed
    report = verify_chain(tmp_path / "s2_seed7_002")
    assert report.problems == [] and report.records[-1].kind == "export"
    head = report.records[-1]
    assert frames[-1].evidence_head == EvidenceHead(
        seq=head.seq, record_hash=head.record_hash
    )
    cards = [a for f in frames for a in f.alerts]
    assert max(a.evidence_records for a in cards) >= 1


async def test_frames_keep_coming_on_the_clock_while_nothing_is_heard(
    live: ModuleType, site: SiteConfig
) -> None:
    labels = ZoneLabels(critical="Pitch", important="Grounds", perimeter="Perimeter")
    clock = SimClock(site.simulation.tick_s, pace=FAST)
    published: list = []
    ticker = asyncio.create_task(
        live.on_time(FrameBuilder("run-1", site, labels), clock, published.append)
    )
    clock.start()
    for _ in range(10):  # 2.0 s of simulated time, and not one message
        await clock.tick()
    await asyncio.sleep(0.05)
    ticker.cancel()
    period = site.dashboard.frame_period_s
    assert [f.t for f in published] == [k * period for k in range(5)]  # a tick behind


@pytest.mark.parametrize(
    ("profile_id", "scenario_id"),
    [("nowhere", "s2"), ("fictional-stadium", "s1"), ("fictional-stadium", "s9")],
)
async def test_only_scenarios_a_profile_has_start(
    live: ModuleType, tmp_path: Path, profile_id: str, scenario_id: str
) -> None:
    request = StartRun(profile_id=profile_id, scenario_id=scenario_id)
    with pytest.raises(LookupError):
        await launcher(live, tmp_path).start(request, print)
    assert not any(tmp_path.iterdir())


async def test_recorded_media_that_is_not_here_is_refused_without_a_folder(
    live: ModuleType, tmp_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    request = S2_SEED_7.model_copy(update={"recorded_media": True})
    with pytest.raises(LookupError, match="recorded media is not ready"):
        await launcher(live, runs_dir, tmp_path / "no-models").start(request, print)
    assert not runs_dir.exists()


def test_s2_runs_end_to_end_through_the_server(
    live: ModuleType, tmp_path: Path
) -> None:
    app = create_app(Hub(launcher(live, tmp_path)), app_dir=tmp_path / "no-app")
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        reply = client.post("/api/runs", json=S2_SEED_7.model_dump())
        assert reply.status_code == 200 and reply.json()["run_id"] == "s2_seed7_001"
        received = until_ended(ws)
        again = client.post("/api/runs", json=S2_SEED_7.model_dump())
        assert again.json()["run_id"] == "s2_seed7_002"  # a new run once one ends
        until_ended(ws)
    frames = [m for m in received if m["type"] == "frame"]
    assert any(f["alerts"] for f in frames)
    assert all(f["run_id"] == "s2_seed7_001" for f in frames)


def until_ended(ws) -> list[dict]:
    received = [ws.receive_json()]
    while not (received[-1]["type"] == "run" and received[-1]["state"] == "ended"):
        received.append(ws.receive_json())
    return received


@pytest.mark.parametrize(
    ("scenario", "profile"),
    [("s1", "fictional-processing-plant"), ("s2", "fictional-stadium")],
)
def test_completed_summary_matches_run_bus_messages(
    live, tmp_path, monkeypatch, scenario, profile
):
    from cuas.schemas import BearingDetection, PicketAlert, ThreatAssessment, Track

    original = live.feed
    batches = []

    async def collect(*args, **kwargs):
        messages = await original(*args, **kwargs)
        batches.extend(messages)
        return messages

    monkeypatch.setattr(live, "feed", collect)
    hub = Hub(launcher(live, tmp_path))
    with TestClient(create_app(hub)) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()
        client.post(
            "/api/runs", json={"profile_id": profile, "scenario_id": scenario}
        ).raise_for_status()
        until_ended(ws)
        summary = client.get("/api/run/summary").json()
        detections = [
            m for m in batches if isinstance(m, BearingDetection | PicketAlert)
        ]
        alerted = {
            m.track_id
            for m in batches
            if isinstance(m, ThreatAssessment) and m.alert_id
        }
        positions = [m for m in batches if isinstance(m, Track)]
        assert summary["ended_reason"] == "completed"
        assert summary["latest_detection"]["t"] == max(m.t for m in detections)
        assert summary["unique_alert_tracks"] == len(alerted)
        assert summary["last_position"]["t"] == max(m.t for m in positions)
        chain = tmp_path / summary["run_id"] / "evidence" / "chain.jsonl"
        assert summary["evidence_records"] == len(chain.read_text().splitlines())
        assert client.get("/api/run/summary").json() == summary
        print(
            scenario,
            {
                k: summary[k]
                for k in (
                    "elapsed_s",
                    "active_alerts",
                    "unique_alert_tracks",
                    "evidence_records",
                    "latest_detection",
                    "last_position",
                )
            },
        )


def test_a_live_run_stopped_while_paused_keeps_valid_evidence_and_frees_the_server(
    live: ModuleType, tmp_path: Path
) -> None:
    real_time = live.LiveLauncher(
        ROOT / "config", ROOT / "data", ROOT / "models", tmp_path
    )
    app = create_app(Hub(real_time), app_dir=tmp_path / "no-app")
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()
        client.post("/api/runs", json=S2_SEED_7.model_dump())
        while ws.receive_json()["type"] != "frame":  # it is under way
            pass
        client.post("/api/run/control", json={"action": "pause"})
        stopped = client.post("/api/run/stop").json()
        assert (stopped["state"], stopped["ended_reason"]) == ("ended", "stopped")
        summary = client.get("/api/run/summary").json()
        assert summary["ended_reason"] == "stopped"
        assert summary["elapsed_s"] < 30
        frames = [m for m in until_ended(ws) if m["type"] == "frame"]
        assert not frames or frames[-1]["t"] < 30.0  # far short of the 120 s scenario
        report = verify_chain(tmp_path / "s2_seed7_001")
        assert report.problems == []
        again = client.post("/api/runs", json=S2_SEED_7.model_dump())
        assert again.status_code == 200 and again.json()["run_id"] == "s2_seed7_002"
        client.post("/api/run/stop")


async def test_missing_and_broken_models_are_named_and_never_shared(
    live: ModuleType, tmp_path: Path
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "look_rgb.pt").write_bytes(b"not a torch file")
    (models / "look_rgb.json").write_text('{"high_score": 0.5}', encoding="utf-8")
    loader = launcher(live, tmp_path / "runs", models)
    published: list[ModelStatus] = []
    await loader.load_models(published.append)
    final = published[-1]
    steps = {s.name: s for s in final.steps}
    assert final.state == "failed"
    assert steps["RGB detector"].state == "failed" and steps["RGB detector"].detail
    assert steps["Thermal detector"].state == "missing"
    assert "look_thermal.pt not found" in steps["Thermal detector"].detail
    assert all(m.state == "loading" for m in published[:-1])
    assert loader._loaded is None


@pytest.mark.media
async def test_models_loaded_once_give_the_same_run_as_models_loaded_per_run(
    live: ModuleType, tmp_path: Path, capsys, monkeypatch
) -> None:
    from cuas.sim import media

    if not (ROOT / "models" / "look_rgb.pt").exists():
        pytest.skip("models not trained here")
    request = S2_SEED_7.model_copy(
        update={"recorded_media": True, "zoom_per_station": 0}
    )
    for preload in (True, False):
        loader = launcher(live, tmp_path / str(preload))
        if preload:
            published: list[ModelStatus] = []
            await loader.load_models(published.append)
            done = [sum(s.state == "ready" for s in m.steps) for m in published]
            assert done == sorted(done) and published[-1].state == "ready"
            assert all(s.state == "ready" for s in published[-1].steps)

            def no_reload(*args) -> None:
                raise AssertionError("a run reloaded the models")

            monkeypatch.setattr(media, "load_look_models", no_reload)
            monkeypatch.setattr(media, "load_sound", no_reload)
        else:
            monkeypatch.undo()
        started = await loader.start(request, lambda message: None)
        await started.done
    digests = re.findall(r"control digest (sha256:\w+)", capsys.readouterr().out)
    assert len(digests) == 2 and digests[0] == digests[1]


async def test_big_drone_camera_detections_are_written_to_the_evidence_chain(
    live: ModuleType, tmp_path: Path
) -> None:
    published: list = []
    request = StartRun(profile_id="fictional-processing-plant", scenario_id="s1")
    started = await launcher(live, tmp_path).start(request, published.append)
    await started.done
    report = verify_chain(tmp_path / started.run.run_id)
    detections = [r for r in report.records if r.kind == "camera_detection"]
    frames = [m for m in published if isinstance(m, Frame)]
    cues = {(c.picket_id, c.detected_t) for f in frames for c in f.cues if c.detected_t}
    assert report.problems == [] and detections
    assert {(r.details["picket_id"], r.t) for r in detections} == cues
    assert all(r.alert_id == "" and r.files == () for r in detections)
