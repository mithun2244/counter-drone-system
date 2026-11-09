"""Live dashboard runs from the composition root (scripts/live_runs.py)."""

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

from cuas.clock import SimClock
from cuas.config import SiteConfig, ZoneLabels
from cuas.dashboard.contract import Frame, StartRun
from cuas.dashboard.frames import FrameBuilder
from cuas.dashboard.server import Hub, create_app

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
    await started.done
    assert started.run.run_id == "s2_seed7_002"
    assert (tmp_path / "s2_seed7_002").is_dir() and started.clips_dir is None
    frames = [m for m in published if isinstance(m, Frame)]
    period = site.dashboard.frame_period_s
    assert [f.t for f in frames] == [k * period for k in range(len(frames))]
    assert frames[-1].t >= started.run.duration_s
    assert any(f.alerts for f in frames)
    _, _, controlled, _ = await record_pipeline("s2", seed=7)
    printed = capsys.readouterr().out
    assert f"control digest sha256:{live.digest(controlled)}" in printed


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
