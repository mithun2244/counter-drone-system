"""Live dashboard runs, wired in the composition root for ``run_demo.py --dashboard``.

Each run gets its own buses, pipeline, clock and frame builder, and a fresh folder
``runs/<scenario>_seed<seed>_<NNN>/``. The simulator plays the scenario as the live sensor feed.
Frames are built from what the gateway accepted and what the control layer published, in the
order they arrive, so a frame can show the control layer one batch behind
(docs/dashboard_contract.md). The simulator's ground truth is dropped here and never reaches the
dashboard. The evidence keeper writes the run's chain, snapshots and hand-off packages into the
run folder, and answers the operator's labels and exports over the evidence bus. When a run
ends, the console gets its control digest: the one ``run_demo.py --scenario ... --fast`` prints
for the same scenario, seed and zoom cameras.

``load_models`` loads the AI models once, off the event loop, as the server starts, and reports
each step; every recorded-media run then shares them. Without it (tests, the plain CLI), a
recorded-media run loads its own.
"""

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable
from functools import partial
from pathlib import Path

from cuas.bus import WILDCARD, Bus, InProcessBus
from cuas.clock import SimClock
from cuas.config import SiteConfig, load_site
from cuas.dashboard.contract import (
    ModelStatus,
    ModelStep,
    RunInfo,
    SiteProfile,
    StartRun,
)
from cuas.dashboard.frames import FrameBuilder, profiles, run_info
from cuas.dashboard.server import Publish, Started
from cuas.evidence.keeper import EvidenceKeeper, start_keeper
from cuas.evidence.store import EvidenceStore, fresh_run_dir
from cuas.media_manifest import dataset_names, load_manifest
from cuas.pipeline import start_pipeline
from cuas.schemas import EvidenceRecord, Message
from cuas.schemas.topics import (
    CAMERA_DETECTION,
    EVIDENCE_RECORD,
    GATEWAY_ACCEPTED,
    ZOOM_TASK,
)
from cuas.sim.engine import run_scenario
from cuas.sim.scenario import Scenario, available_scenarios, load_scenario
from cuas.sim.station import LookSource

REAL_TIME = 1.0
LOOK_STEPS = {"rgb": "RGB detector", "thermal": "Thermal detector"}
SOUND_STEP, WARM_UP_STEP = "Sound classifier", "Warm-up inference"


def digest(messages: list[Message]) -> str:
    """As ``run_demo.py`` hashes the control bus."""
    hashed = hashlib.sha256()
    for message in messages:
        hashed.update(
            f"{type(message).__name__} {message.model_dump_json()}\n".encode()
        )
    return hashed.hexdigest()


async def feed(
    builder: FrameBuilder,
    tap: AsyncIterator[Message],
    publish: Publish,
    evidence: Bus | None = None,
) -> list[Message]:
    """Pass every message to the frame builder and publish its frames. Returns the messages.
    An evidence record also sends the latest frame again, so a label shows while paused.
    Big-drone camera detections the builder notices go to the evidence keeper."""
    seen = []
    async for message in tap:
        seen.append(message)
        for frame in builder.ingest(message):
            publish(frame)
        for note in builder.take_camera_detections():
            await _note(evidence, note)
        if isinstance(message, EvidenceRecord) and (frame := builder.again()):
            publish(frame)
    return seen


async def _note(evidence: Bus | None, note: Message) -> None:
    if evidence is None:
        return
    try:
        await evidence.publish(CAMERA_DETECTION, note)
    except (
        RuntimeError
    ):  # the evidence bus closed as the run ended: nothing left to record
        return


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
        self._loaded = None

    def profiles(self) -> list[SiteProfile]:
        return self._profiles

    async def load_models(self, publish: Callable[[ModelStatus], None]) -> None:
        """Load every model once in a worker thread, publishing each step, so the server keeps
        serving. Recorded-media runs share them once this ends ``ready``. A model that fails
        is named with the error; simulator runs never need the models."""
        from cuas.sim.media import (
            SOUND_WEIGHTS,
            LoadedModels,
            load_look_model,
            load_sound,
            look_weights,
            warm_up,
        )
        from cuas.station.detector import use_inference_threads

        ai = load_site(self._config_dir).station_ai
        steps = _Steps([*LOOK_STEPS.values(), SOUND_STEP, WARM_UP_STEP], publish)
        looks = {}
        for sensor, name in LOOK_STEPS.items():
            missing = (
                f"{look_weights(self._models_dir, sensor).name} not found in models/"
            )
            load = partial(load_look_model, self._models_dir, ai.detector, sensor)
            if (model := await steps.attempt(name, load, missing)) is not None:
                looks[sensor] = model
        missing = f"{SOUND_WEIGHTS} not found in models/"
        sound = await steps.attempt(
            SOUND_STEP, partial(load_sound, self._models_dir, ai), missing
        )
        loaded = LoadedModels(looks, sound)
        if looks:
            await steps.attempt(WARM_UP_STEP, partial(_warmed, warm_up, loaded, ai), "")
        else:
            steps.report(WARM_UP_STEP, "missing", "no camera model to warm up")
        use_inference_threads(ai.detector)  # in the loop's thread, where inference runs
        if looks and not steps.failed:
            self._loaded = loaded
        steps.finish(ready=self._loaded is not None)

    async def start(self, request: StartRun, publish: Publish) -> Started:
        scenario = self._scenario(request)
        site = load_site(self._config_dir, zoom_per_station=request.zoom_per_station)
        seed = scenario.seed if request.seed is None else request.seed
        run_dir = fresh_run_dir(self._runs_dir, f"{scenario.metadata.id}_seed{seed}")
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
        evidence = InProcessBus()
        done = asyncio.create_task(
            self._run(run, scenario, site, media, clock, publish, evidence, run_dir)
        )
        clips = run_dir if media is not None else None
        return Started(run, clock, self._pace, clips, done, run_dir, evidence)

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
        """Imported only when asked for, so simulator-only runs never load torch. Uses the
        models ``load_models`` loaded, if it ran; otherwise loads them here, in the loop."""
        if not request.recorded_media:
            return None
        from cuas.sim.media import build_media_link

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
                self._loaded,
            )
        except FileNotFoundError as error:
            raise LookupError(f"recorded media is not ready: {error}") from error

    async def _run(
        self,
        run: RunInfo,
        scenario: Scenario,
        site: SiteConfig,
        media: LookSource | None,
        clock: SimClock,
        publish: Publish,
        evidence: InProcessBus,
        run_dir: Path,
    ) -> None:
        sensor, ingest, control = InProcessBus(), InProcessBus(), InProcessBus()
        labels = scenario.metadata.zone_labels
        datasets = (
            {} if media is None else dataset_names(load_manifest(self._config_dir))
        )
        builder = FrameBuilder(run.run_id, site, labels, datasets)
        store = EvidenceStore(run_dir)
        keeper = start_keeper(
            EvidenceKeeper(store, run.run_id, labels), control, evidence
        )
        taps = (
            ingest.subscribe(GATEWAY_ACCEPTED),
            control.subscribe(WILDCARD),
            evidence.subscribe(EVIDENCE_RECORD),
        )
        feeds = [
            asyncio.create_task(feed(builder, tap, publish, evidence)) for tap in taps
        ]
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
                seed=run.seed,
                media=media,
                zoom_tasks=zoom_tasks,
            )
        finally:
            ticker.cancel()
            await sensor.close()  # so the pipeline and feeds end even if the run fails
        await pipeline
        await keeper  # it exports every alert, then closes the evidence bus
        _, controlled, records = await asyncio.gather(*feeds)
        publish(builder.flush())
        print(f"run {run.run_id} ended: control digest sha256:{digest(controlled)}")
        print(f"  {len(records)} evidence records; check: uv run cuas verify {run_dir}")


def _warmed(warm_up: Callable, models: object, settings: object) -> bool:
    """True, so the warm-up step reads ready rather than missing."""
    warm_up(models, settings)
    return True


class _Steps:
    """The steps of loading the models, published to the dashboard as each one changes."""

    def __init__(
        self, names: list[str], publish: Callable[[ModelStatus], None]
    ) -> None:
        self._steps = {name: ModelStep(name=name, state="waiting") for name in names}
        self._publish = publish

    @property
    def failed(self) -> bool:
        return any(step.state == "failed" for step in self._steps.values())

    def report(self, name: str, state: str, detail: str | None = None) -> None:
        self._steps[name] = ModelStep(name=name, state=state, detail=detail)
        self._publish(ModelStatus(state="loading", steps=list(self._steps.values())))

    def finish(self, ready: bool) -> None:
        state = "ready" if ready else "failed"
        self._publish(ModelStatus(state=state, steps=list(self._steps.values())))

    async def attempt(self, name: str, load: Callable[[], object], missing: str):
        """Run one load in a worker thread. ``None`` back means the weights are not there."""
        self.report(name, "loading")
        try:
            result = await asyncio.to_thread(load)
        except Exception as error:  # noqa: BLE001 -- any load error goes to the operator's panel, naming the model
            self.report(name, "failed", f"{type(error).__name__}: {error}")
            return None
        if result is None:
            self.report(name, "missing", missing)
        else:
            self.report(name, "ready")
        return result
