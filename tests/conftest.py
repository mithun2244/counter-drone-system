from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from cuas.bus import WILDCARD, InProcessBus
from cuas.clock import SimClock
from cuas.config import SiteConfig, load_site
from cuas.pipeline import start_pipeline
from cuas.schemas import Message
from cuas.sim.engine import run_scenario
from cuas.sim.scenario import Scenario, load_scenario
from cuas.sim.truth import TruthLog

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
    ) -> RecordedPipeline:
        site = load_site(config_dir)
        if isinstance(scenario, str):
            scenario = load_scenario(config_dir, scenario)
        sensor, ingest, control = InProcessBus(), InProcessBus(), InProcessBus()
        clock = SimClock(site.simulation.tick_s, pace=pace)
        taps = [bus.subscribe(WILDCARD) for bus in (sensor, ingest, control)]
        labels = scenario.metadata.zone_labels
        pipeline = start_pipeline(
            sensor, ingest, control, site, labels, lambda: clock.now
        )
        truth = await run_scenario(
            scenario, site, sensor, clock, seed=seed, media=media
        )
        await sensor.close()
        await pipeline
        sensed, ingested, controlled = [[m async for m in tap] for tap in taps]
        return sensed, ingested, controlled, truth

    return _record
