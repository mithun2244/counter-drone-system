"""Live dashboard runs, wired in the composition root for ``run_demo.py --dashboard``.

Each run gets its own buses, pipeline, clock and frame builder, and a fresh folder
``runs/<scenario>_seed<seed>_<NNN>/``. The simulator plays the scenario as the live sensor feed.
Frames are built from what the gateway accepted and what the control layer published, in the
order they arrive, so a frame can show the control layer one batch behind
(docs/dashboard_contract.md). The simulator's ground truth is dropped here and never reaches the
dashboard. When a run ends, the console gets its control digest: the one
``run_demo.py --scenario ... --fast`` prints for the same scenario, seed and zoom cameras.
"""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from itertools import count
from pathlib import Path

from cuas.bus import WILDCARD, InProcessBus
from cuas.clock import SimClock
from cuas.config import SiteConfig, load_site
from cuas.dashboard.contract import SiteProfile, StartRun
from cuas.dashboard.frames import FrameBuilder, profiles, run_info
from cuas.dashboard.server import Publish, Started
from cuas.pipeline import start_pipeline
from cuas.schemas import Message
from cuas.schemas.topics import GATEWAY_ACCEPTED, ZOOM_TASK
from cuas.sim.engine import run_scenario
from cuas.sim.scenario import Scenario, available_scenarios, load_scenario
from cuas.sim.station import LookSource

REAL_TIME = 1.0


def digest(messages: list[Message]) -> str:
    """As ``run_demo.py`` hashes the control bus."""
    hashed = hashlib.sha256()
    for message in messages:
        hashed.update(
            f"{type(message).__name__} {message.model_dump_json()}\n".encode()
        )
    return hashed.hexdigest()


def fresh_folder(runs_dir: Path, stem: str) -> Path:
    """The first ``<stem>_<NNN>`` not taken, so no run overwrites or mixes with another."""
    for n in count(1):
        path = runs_dir / f"{stem}_{n:03d}"
        if not path.exists():
            return path
    raise AssertionError("unreachable")


async def feed(
    builder: FrameBuilder, tap: AsyncIterator[Message], publish: Publish
) -> list[Message]:
    """Pass every message to the frame builder and publish its frames. Returns the messages."""
    seen = []
    async for message in tap:
        seen.append(message)
        for frame in builder.ingest(message):
            publish(frame)
    return seen


async def on_time(builder: FrameBuilder, clock: SimClock, publish: Publish) -> None:
    """Frames on the clock as well, so they keep coming while nothing is heard. One tick behind
    it, so a mark's observations were published a tick earlier."""
    while True:
        await asyncio.sleep(clock.tick_s / clock.pace)
        for frame in builder.advance(clock.now - clock.tick_s):
            publish(frame)


class LiveLauncher:
    def __init__(
        self,
        config_dir: Path,
        data_dir: Path,
        models_dir: Path,
        runs_dir: Path,
        pace: float = REAL_TIME,
    ) -> None:
        self._config_dir = config_dir
        self._data_dir = data_dir
        self._models_dir = models_dir
        self._runs_dir = runs_dir
        self._pace = pace
        loaded = [load_scenario(config_dir, s) for s in available_scenarios(config_dir)]
        self._scenarios = {s.metadata.id: s for s in loaded}
        self._profiles = profiles([s.metadata for s in loaded])

    def profiles(self) -> list[SiteProfile]:
        return self._profiles

    async def start(self, request: StartRun, publish: Publish) -> Started:
        scenario = self._scenario(request)
        site = load_site(self._config_dir, zoom_per_station=request.zoom_per_station)
        seed = scenario.seed if request.seed is None else request.seed
        run_dir = fresh_folder(self._runs_dir, f"{scenario.metadata.id}_seed{seed}")
        media = self._media(request, site, scenario, seed, run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        run = run_info(
            run_dir.name,
            scenario.metadata,
            self._profiles,
            site,
            seed,
            scenario.duration_s,
            media is not None,
        )
        clock = SimClock(site.simulation.tick_s, pace=self._pace)
        print(f"run {run.run_id} started, folder {run_dir}")
        done = asyncio.create_task(
            self._run(run.run_id, scenario, site, seed, media, clock, publish)
        )
        clips = run_dir if media is not None else None
        return Started(run, clock, self._pace, clips, done)

    def _scenario(self, request: StartRun) -> Scenario:
        profile = next(
            (p for p in self._profiles if p.profile_id == request.profile_id), None
        )
        if profile is None:
            raise LookupError(f"no site profile {request.profile_id!r}")
        if request.scenario_id not in {s.scenario_id for s in profile.scenarios}:
            raise LookupError(
                f"{profile.venue} has no scenario {request.scenario_id!r}"
            )
        return self._scenarios[request.scenario_id]

    def _media(
        self,
        request: StartRun,
        site: SiteConfig,
        scenario: Scenario,
        seed: int,
        run_dir: Path,
    ) -> LookSource | None:
        """Imported only when asked for, so simulator-only runs never load torch."""
        if not request.recorded_media:
            return None
        from cuas.sim.media import build_media_link

        # ponytail: loads the models in the event loop, so the server stalls for a few
        # seconds before a recorded-media run; move it to a thread if that matters.
        try:
            return build_media_link(
                self._config_dir,
                self._data_dir,
                self._models_dir,
                run_dir,
                site.station_ai,
                site.simulation.tick_s,
                scenario.environment.wind_mps,
                seed,
            )
        except FileNotFoundError as error:
            raise LookupError(f"recorded media is not ready: {error}") from error

    async def _run(
        self,
        run_id: str,
        scenario: Scenario,
        site: SiteConfig,
        seed: int,
        media: LookSource | None,
        clock: SimClock,
        publish: Publish,
    ) -> None:
        sensor, ingest, control = InProcessBus(), InProcessBus(), InProcessBus()
        labels = scenario.metadata.zone_labels
        builder = FrameBuilder(run_id, site, labels)
        taps = (ingest.subscribe(GATEWAY_ACCEPTED), control.subscribe(WILDCARD))
        feeds = [asyncio.create_task(feed(builder, tap, publish)) for tap in taps]
        ticker = asyncio.create_task(on_time(builder, clock, publish))
        zoom_tasks = control.subscribe(ZOOM_TASK)
        pipeline = start_pipeline(
            sensor, ingest, control, site, labels, lambda: clock.now
        )
        try:
            await run_scenario(  # its ground truth is dropped here
                scenario,
                site,
                sensor,
                clock,
                seed=seed,
                media=media,
                zoom_tasks=zoom_tasks,
            )
        finally:
            ticker.cancel()
            await sensor.close()  # so the pipeline and feeds end even if the run fails
        await pipeline
        _, controlled = await asyncio.gather(*feeds)
        publish(builder.flush())
        print(f"run {run_id} ended: control digest sha256:{digest(controlled)}")
