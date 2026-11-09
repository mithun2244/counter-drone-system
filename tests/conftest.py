from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from cuas.bus import WILDCARD, InProcessBus
from cuas.clock import SimClock
from cuas.config import SiteConfig, ZoneLabels, load_site
from cuas.evidence.keeper import EvidenceKeeper
from cuas.evidence.store import EvidenceStore
from cuas.pipeline import start_pipeline
from cuas.schemas import (
    ClueEvidence,
    ExportRequest,
    Message,
    OperatorLabel,
    ThreatAssessment,
    Track,
    TrackClass,
)
from cuas.schemas.topics import ZOOM_TASK
from cuas.sim.engine import run_scenario
from cuas.sim.scenario import Scenario, load_scenario
from cuas.sim.truth import TruthLog
from cuas.station.recorder import Recorder

ROOT = Path(__file__).resolve().parents[1]

Recorded = tuple[list[Message], TruthLog]
RecordedPipeline = tuple[list[Message], list[Message], list[Message], TruthLog]


@pytest.fixture
def config_dir() -> Path:
    return ROOT / "config"


@pytest.fixture
def site(config_dir: Path) -> SiteConfig:
    return load_site(config_dir)


@pytest.fixture
def record(config_dir: Path) -> Callable[..., Awaitable[Recorded]]:
    """Run a scenario by ID (or a ``Scenario``) and return every message in publish order."""

    async def _record(
        scenario: str | Scenario,
        seed: int | None = None,
        *,
        pace: float | None = None,
        zoom: int = 1,
        media: object = None,
    ) -> Recorded:
        site = load_site(config_dir, zoom_per_station=zoom)
        if isinstance(scenario, str):
            scenario = load_scenario(config_dir, scenario)
        bus, clock = InProcessBus(), SimClock(site.simulation.tick_s, pace=pace)
        tap = bus.subscribe(WILDCARD)  # every message, in exact publish order
        truth = await run_scenario(scenario, site, bus, clock, seed=seed, media=media)
        await bus.close()
        return [message async for message in tap], truth

    return _record


@pytest.fixture
def record_pipeline(config_dir: Path) -> Callable[..., Awaitable[RecordedPipeline]]:
    """Run a scenario through the gateway and control layer.

    Returns what the sensor, ingest and control buses carried, each in publish order, and truth.
    """

    async def _record(
        scenario: str | Scenario,
        seed: int | None = None,
        *,
        pace: float | None = None,
        media: object = None,
        zoom: int | None = None,
    ) -> RecordedPipeline:
        site = load_site(config_dir, zoom_per_station=zoom)
        if isinstance(scenario, str):
            scenario = load_scenario(config_dir, scenario)
        sensor, ingest, control = InProcessBus(), InProcessBus(), InProcessBus()
        clock = SimClock(site.simulation.tick_s, pace=pace)
        taps = [bus.subscribe(WILDCARD) for bus in (sensor, ingest, control)]
        labels = scenario.metadata.zone_labels
        zoom_tasks = control.subscribe(ZOOM_TASK)
        pipeline = start_pipeline(
            sensor, ingest, control, site, labels, lambda: clock.now
        )
        truth = await run_scenario(
            scenario, site, sensor, clock, seed=seed, media=media, zoom_tasks=zoom_tasks
        )
        await sensor.close()
        await pipeline
        sensed, ingested, controlled = [[m async for m in tap] for tap in taps]
        return sensed, ingested, controlled, truth

    return _record


CLIP_ID = "abcdef0123456789"
STADIUM_LABELS = ZoneLabels(
    critical="Pitch", important="Grounds", perimeter="Perimeter"
)


@pytest.fixture
def finished_run(tmp_path: Path) -> Path:
    """A finished run's folder, made by the real evidence keeper: one recording, an alert raised
    amber that turns red, an operator label and export, and the exports at run end."""
    run_dir = tmp_path / "run"
    Recorder(run_dir).save("st1", CLIP_ID, ".mp4", b"recorded clip")
    keeper = EvidenceKeeper(EvidenceStore(run_dir), "run-1", STADIUM_LABELS)
    cov = tuple(tuple(1.0 if i == j else 0.0 for j in range(6)) for i in range(6))
    for t, level in [(1.0, "amber"), (1.2, "red")]:
        keeper.ingest(
            Track(
                track_id="trk-1",
                t=t,
                position_enu_m=(-300.0 + 10 * t, 100.0, 60.0),
                velocity_mps=(10.0, 0.0, 0.0),
                covariance=cov,
                n_stations=3,
                status="confirmed",
            )
        )
        keeper.ingest(
            TrackClass(
                track_id="trk-1",
                t=t,
                p_drone=0.9,
                p_bird=0.1,
                p_attack_drone=0.0,
                evidence=ClueEvidence(look=0.9),
                looks={"st1.rgb": f"{CLIP_ID}:3"},
            )
        )
        keeper.ingest(
            ThreatAssessment(
                track_id="trk-1",
                t=t,
                score=0.8,
                level=level,
                zone="critical",
                time_to_impact_s=20.0,
                reasons=("heading to Pitch, 20 s",),
                alert_id="alert-1",
            )
        )
    keeper.handle(
        OperatorLabel(alert_id="alert-1", label="confirm", t=2.0, request_id="req-1")
    )
    keeper.handle(ExportRequest(alert_id="alert-1", t=3.0, request_id="req-2"))
    keeper.finish()
    return run_dir
