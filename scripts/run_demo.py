"""Demo entry point. With no arguments, load the site config and report what it holds.

With ``--scenario``, run that scenario and print what the sensors report, then what the gateway
and the shared tracker made of it. The output depends only on the scenario, seed and config, so
two runs with the same inputs are byte-identical, in fast mode or real time. Ground truth reaches
only the evaluator; its ``[evaluator]`` lines are the only output that names targets.

With ``--evidence``, the evidence keeper also writes the run's chain, snapshots and hand-off
packages into a fresh ``runs/<scenario>_seed<seed>_<NNN>/`` folder, for ``cuas verify``.

With ``--dashboard``, serve the dashboard locally. The operator picks a site profile and starts
live runs from it (``live_runs.py``), or with ``--replay`` plays a recorded contract stream.
"""

import argparse
import asyncio
import hashlib
import sys
from collections.abc import AsyncIterator
from pathlib import Path

from cuas.bus import WILDCARD, InProcessBus
from cuas.clock import SimClock
from cuas.config import SiteConfig, load_site
from cuas.evidence.keeper import EvidenceKeeper, start_keeper
from cuas.evidence.store import EvidenceStore, fresh_run_dir
from cuas.metrics.alert_evaluator import AlertReport, evaluate_alerts
from cuas.metrics.evaluator import TargetSummary, summarize
from cuas.metrics.track_evaluator import TrackReport, evaluate_tracks
from cuas.pipeline import start_pipeline
from cuas.schemas import (
    BearingDetection,
    CoverageStatus,
    Message,
    PicketAlert,
    SectorTrack,
    ThreatAssessment,
    Track,
    ZoomTask,
)
from cuas.schemas.topics import GATEWAY_REJECTED, ZOOM_TASK
from cuas.sim.engine import run_scenario
from cuas.sim.scenario import Scenario, available_scenarios, load_scenario
from cuas.sim.station import LookSource

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
MODELS_DIR = ROOT / "models"
USAGE_ERROR = 2
REAL_TIME_PACE = 1.0


def non_negative_int(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must not be negative: {text}")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", choices=available_scenarios(CONFIG_DIR))
    parser.add_argument(
        "--fast", action="store_true", help="run as fast as possible, not in real time"
    )
    parser.add_argument(
        "--seed",
        type=non_negative_int,
        help="sensor noise seed (default: the scenario's)",
    )
    parser.add_argument(
        "--zoom-per-station",
        type=int,
        choices=[0, 1, 2],
        help="zoom cameras per station (default: the value in site.yaml)",
    )
    parser.add_argument(
        "--recorded-media",
        action="store_true",
        help="run real models on held-out recordings for look evidence",
    )
    parser.add_argument(
        "--evidence",
        action="store_true",
        help="with --scenario: keep evidence in a fresh folder under runs/",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="serve the dashboard locally; the operator starts runs from it",
    )
    parser.add_argument(
        "--replay",
        type=Path,
        help="with --dashboard: play a recorded contract stream instead of live runs",
    )
    parser.add_argument("--port", type=int, help="dashboard port (default: site.yaml)")
    return parser.parse_args()


def describe_look(bearing: BearingDetection) -> str:
    if not bearing.class_probs:
        return ""
    scores = ",".join(f"{k}:{v:.2f}" for k, v in bearing.class_probs.items())
    return f" look={scores} clip={bearing.snapshot_ref}"


def describe(message: Message) -> str | None:
    """One line for a bearing or picket alert. Status reports count in the digest only."""
    if isinstance(message, BearingDetection):
        return (
            f"t={message.t:.3f} bearing {message.station_id} {message.sensor} "
            f"az={message.azimuth_deg:.3f} el={message.elevation_deg:.3f} "
            f"sigma={message.sigma_deg}{describe_look(message)}"
        )
    if isinstance(message, PicketAlert):
        engines = ",".join(
            f"{engine}:{p:.2f}" for engine, p in message.engine_type_probs.items()
        )
        return (
            f"t={message.t:.3f} picket {message.picket_id} "
            f"bearing={message.bearing_deg:.1f} loudness={message.loudness:.2f} "
            f"engine={engines}"
        )
    return None


async def print_observations(subscription: AsyncIterator[Message]) -> None:
    """Print observations as they arrive, then a summary and a digest of the whole stream."""
    digest = hashlib.sha256()
    bearings, alerts, total = 0, 0, 0
    stations: set[str] = set()
    async for message in subscription:
        total += 1
        digest.update(
            f"{type(message).__name__} {message.model_dump_json()}\n".encode()
        )
        if isinstance(message, BearingDetection):
            bearings += 1
            stations.add(message.station_id)
        alerts += isinstance(message, PicketAlert)
        if line := describe(message):
            print(line)
    print(
        f"observations: {bearings} bearings from {len(stations)} stations "
        f"({', '.join(sorted(stations))}), {alerts} picket alerts, {total} messages"
    )
    print(f"digest: sha256:{digest.hexdigest()}")


async def collect(subscription: AsyncIterator[Message]) -> list[Message]:
    return [message async for message in subscription]


def describe_control(message: Message, shown: dict[str, str]) -> str | None:
    """A line when a track or sector starts or changes status, so the output stays short."""
    if isinstance(message, Track):
        if shown.get(message.track_id) == message.status:
            return None
        shown[message.track_id] = message.status
        x, y, z = message.position_enu_m
        return (
            f"t={message.t:.3f} track {message.track_id} {message.status} "
            f"pos=({x:.1f},{y:.1f},{z:.1f}) stations={message.n_stations}"
        )
    if isinstance(message, ThreatAssessment) and message.alert_id is not None:
        state = f"{message.level} {message.track_id}"
        if shown.get(message.alert_id) == state:
            return None
        shown[message.alert_id] = state
        tti = message.time_to_impact_s
        when = "none" if tti is None else f"{tti:.0f}s"
        return (
            f"t={message.t:.3f} alert {message.alert_id} {message.track_id} "
            f"{message.level} score={message.score:.2f} tti={when} "
            f"reasons: {'; '.join(message.reasons)}"
        )
    if isinstance(message, CoverageStatus):
        return (
            f"t={message.t:.3f} coverage {message.coverage_pct:.1f}%"
            f"{' warning' if message.warning else ''}"
        )
    if isinstance(message, SectorTrack):
        if shown.get(message.sector_id) == message.status:
            return None
        shown[message.sector_id] = message.status
        return (
            f"t={message.t:.3f} sector {message.sector_id} {message.sensor_id} "
            f"{message.status} bearing={message.bearing_deg:.1f} "
            f"half_width={message.half_width_deg:.1f}"
        )
    return None


def print_control(messages: list[Message], rejected: list[Message]) -> None:
    """Printed after the run, so fast and real-time runs print the same lines in the same order."""
    digest = hashlib.sha256()
    shown: dict[str, str] = {}
    for message in messages:
        digest.update(
            f"{type(message).__name__} {message.model_dump_json()}\n".encode()
        )
        if line := describe_control(message, shown):
            print(line)
    tracks = [m for m in messages if isinstance(m, Track)]
    confirmed = {t.track_id for t in tracks if t.status == "confirmed"}
    sectors = {m.sector_id for m in messages if isinstance(m, SectorTrack)}
    threats = [m for m in messages if isinstance(m, ThreatAssessment)]
    alerts = {m.alert_id for m in threats if m.alert_id is not None}
    reds = {m.alert_id for m in threats if m.level == "red"}
    zooms = sum(isinstance(m, ZoomTask) for m in messages)
    print(
        f"control: {len({t.track_id for t in tracks})} tracks started, "
        f"{len(confirmed)} confirmed, {len(sectors)} sectors, {len(alerts)} alerts "
        f"({len(reds)} red), {zooms} zoom tasks, {len(rejected)} messages rejected"
    )
    print(f"control digest: sha256:{digest.hexdigest()}")


def print_header(scenario: Scenario, site: SiteConfig, seed: int) -> None:
    labels = scenario.metadata.zone_labels
    print(f"scenario {scenario.metadata.id}: {scenario.metadata.title}")
    print(f"venue: {scenario.metadata.venue}")
    print(
        f"zones: critical={labels.critical}, important={labels.important}, "
        f"perimeter={labels.perimeter}"
    )
    print(f"seed: {seed}")
    print(
        f"zoom_per_station: {site.zoom_per_station} (zoom looks need --recorded-media)"
    )


def print_evaluation(summaries: list[TargetSummary]) -> None:
    print("[evaluator] simulator results, not real-world performance")
    for summary in summaries:
        seen = " ".join(f"{k}={v}" for k, v in summary.bearings_by_station.items())
        warning = (
            "" if summary.warning_s is None else f" warning={summary.warning_s:.1f}s"
        )
        print(
            f"[evaluator] {summary.target_id} {summary.target_type}: bearings {seen or 'none'}{warning}"
        )


def print_track_evaluation(report: TrackReport) -> None:
    drones, birds = report.drones_tracked, report.birds_tracked
    print(
        f"[evaluator] tracks: {report.confirmed} confirmed, {report.false_tracks} false, "
        f"{report.overlapping_duplicates} overlapping and {report.sequential_duplicates} "
        f"sequential duplicates; drones tracked {drones[0]} of {drones[1]}, "
        f"birds {birds[0]} of {birds[1]}"
    )
    if report.median_error_m is None:
        print("[evaluator] position error: no confirmed track to score")
    else:
        worst, worst_m = report.worst_target
        print(
            "[evaluator] position error on confirmed tracks while their target flies: "
            f"median {report.median_error_m:.2f} m, p95 {report.p95_error_m:.2f} m, "
            f"worst target {worst} at {worst_m:.2f} m; {report.scored} messages scored, "
            f"{report.after_flight} after the flight ended"
        )
    for target, count in report.tracks_per_target.items():
        first = report.first_confirmed.get(target)
        when = (
            ""
            if first is None
            else f", first confirmed at t={first[0]:.1f} s, {first[1]:.0f} m from the site centre"
        )
        print(f"[evaluator] {target}: {count} confirmed track(s){when}")


def print_alert_evaluation(report: AlertReport) -> None:
    print(
        f"[evaluator] alerts: {len(report.alert_owner)} raised, {report.wrong_alarms} amber or "
        f"red assessments on birds, false or unconfirmed tracks, {report.stale_rises} "
        "rises without a fresh fix"
    )
    print(
        f"[evaluator] red order: {report.red_batches} batches with 2 or more reds, "
        f"{report.out_of_order_batches} out of true arrival order"
    )
    for target, count in report.alerts_per_target.items():
        red = report.first_red.get(target)
        when = (
            ""
            if red is None
            else f", first red at t={red[0]:.1f} s, {red[1]:.1f} s after its track started"
        )
        print(f"[evaluator] {target}: {count} alert(s){when}")
    if report.coverage:
        lowest = min(pct for _, pct, _ in report.coverage)
        warned = any(warning for _, _, warning in report.coverage)
        print(
            f"[evaluator] coverage: lowest {lowest:.1f}%, warning {'set' if warned else 'not set'}"
        )


def build_media(
    args: argparse.Namespace,
    site: SiteConfig,
    wind_mps: float,
    seed: int,
    run_dir: Path | None,
) -> LookSource | None:
    """Imported only when asked for, so simulator-only runs never load torch."""
    if not args.recorded_media:
        return None
    from cuas.sim.media import build_media_link

    return build_media_link(
        CONFIG_DIR,
        DATA_DIR,
        MODELS_DIR,
        run_dir or ROOT / "runs" / f"{args.scenario}_seed{seed}",
        site.station_ai,
        site.simulation.tick_s,
        wind_mps,
        seed,
    )


def keep_evidence(
    scenario: Scenario, seed: int, control_bus: InProcessBus
) -> tuple[EvidenceStore, asyncio.Task[None]]:
    """Subscribe the evidence keeper to the control bus, writing into a fresh run folder."""
    run_dir = fresh_run_dir(ROOT / "runs", f"{scenario.metadata.id}_seed{seed}")
    store = EvidenceStore(run_dir)
    keeper = EvidenceKeeper(store, run_dir.name, scenario.metadata.zone_labels)
    return store, start_keeper(keeper, control_bus, InProcessBus())


async def run(args: argparse.Namespace, site: SiteConfig) -> None:
    scenario = load_scenario(CONFIG_DIR, args.scenario)
    seed = scenario.seed if args.seed is None else args.seed
    print_header(scenario, site, seed)
    sensor_bus, ingest_bus, control_bus = InProcessBus(), InProcessBus(), InProcessBus()
    clock = SimClock(site.simulation.tick_s, pace=None if args.fast else REAL_TIME_PACE)
    evidence = keep_evidence(scenario, seed, control_bus) if args.evidence else None
    run_dir = None if evidence is None else evidence[0].run_dir
    printer = asyncio.create_task(print_observations(sensor_bus.subscribe(WILDCARD)))
    outputs = asyncio.create_task(collect(control_bus.subscribe(WILDCARD)))
    rejected = asyncio.create_task(collect(ingest_bus.subscribe(GATEWAY_REJECTED)))
    pipeline = start_pipeline(
        sensor_bus,
        ingest_bus,
        control_bus,
        site,
        scenario.metadata.zone_labels,
        lambda: clock.now,
    )
    media = build_media(args, site, scenario.environment.wind_mps, seed, run_dir)
    truth = await run_scenario(
        scenario,
        site,
        sensor_bus,
        clock,
        seed=seed,
        media=media,
        zoom_tasks=control_bus.subscribe(ZOOM_TASK),
    )
    await sensor_bus.close()
    await printer
    await pipeline
    controlled = await outputs
    print_control(controlled, await rejected)
    if evidence is not None:
        store, keeper = evidence
        await keeper
        records = 0 if store.head is None else store.head.seq
        print(f"evidence: {records} records in {run_dir}")
        print(f"check it with: uv run cuas verify {run_dir}")
    print_evaluation(summarize(truth))
    tracks = [m for m in controlled if isinstance(m, Track)]
    print_track_evaluation(evaluate_tracks(truth, tracks))
    print_alert_evaluation(evaluate_alerts(truth, controlled))


async def serve_dashboard(args: argparse.Namespace, site: SiteConfig) -> None:
    from live_runs import LiveLauncher

    from cuas.dashboard.basemap import StaleBasemap, load_basemap
    from cuas.dashboard.replay import ReplayLauncher
    from cuas.dashboard.server import Hub, Launcher, create_app, serve

    launcher: Launcher
    if args.replay is None:
        launcher = LiveLauncher(CONFIG_DIR, DATA_DIR, MODELS_DIR, ROOT / "runs")
    else:
        launcher = ReplayLauncher(args.replay, site.simulation.tick_s)
    try:
        basemap = load_basemap(DATA_DIR, site.dashboard.basemap)
    except StaleBasemap as error:
        raise SystemExit(str(error)) from error
    host, port = site.dashboard.host, args.port or site.dashboard.port
    print(f"dashboard: http://{host}:{port}/  (reference page: /reference/)")
    print(
        f"basemap: {basemap.name}, fetched {basemap.fetched}"
        if basemap
        else "basemap: none (scripts/fetch_basemap.py); the local grid is drawn"
    )
    hub = Hub(launcher)
    loading = None
    if isinstance(launcher, LiveLauncher):  # off the event loop: the page never freezes
        loading = asyncio.create_task(launcher.load_models(hub.publish))
    await serve(create_app(hub, basemap=basemap), host, port)
    if loading is not None:
        loading.cancel()


def main() -> None:
    args = parse_args()
    if args.replay and not args.dashboard:
        print("--replay needs --dashboard", file=sys.stderr)
        sys.exit(USAGE_ERROR)
    if args.evidence and not args.scenario:
        print("--evidence needs --scenario", file=sys.stderr)
        sys.exit(USAGE_ERROR)
    site = load_site(CONFIG_DIR, zoom_per_station=args.zoom_per_station)
    if args.dashboard:
        asyncio.run(serve_dashboard(args, site))
        return
    print("hello")
    print(
        f"loaded site.yaml: {len(site.stations)} stations, "
        f"{len(site.pickets)} pickets, {len(site.zones)} zones"
    )
    if args.scenario:
        try:
            asyncio.run(run(args, site))
        except FileNotFoundError as error:
            print(f"recorded media is not ready: {error}", file=sys.stderr)
            sys.exit(USAGE_ERROR)


if __name__ == "__main__":
    main()
