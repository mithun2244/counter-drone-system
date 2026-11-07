"""Demo entry point. With no arguments, load the site config and report what it holds.

With ``--scenario``, run that scenario and print what the sensors report. The output depends only
on the scenario, seed and config, so two runs with the same inputs are byte-identical, in fast mode
or real time. Ground truth reaches only the evaluator; its ``[evaluator]`` lines are the only
output that names targets.
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
from cuas.metrics.evaluator import TargetSummary, summarize
from cuas.schemas import BearingDetection, Message, PicketAlert
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


def print_header(scenario: Scenario, site: SiteConfig, seed: int) -> None:
    labels = scenario.metadata.zone_labels
    print(f"scenario {scenario.metadata.id}: {scenario.metadata.title}")
    print(f"venue: {scenario.metadata.venue}")
    print(
        f"zones: critical={labels.critical}, important={labels.important}, "
        f"perimeter={labels.perimeter}"
    )
    print(f"seed: {seed}")
    print(f"zoom_per_station: {site.zoom_per_station} (not used until Phase 4)")


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


def build_media(
    args: argparse.Namespace, site: SiteConfig, wind_mps: float, seed: int
) -> LookSource | None:
    """Imported only when asked for, so simulator-only runs never load torch."""
    if not args.recorded_media:
        return None
    from cuas.sim.media import build_media_link

    return build_media_link(
        CONFIG_DIR,
        DATA_DIR,
        MODELS_DIR,
        site.station_ai,
        site.simulation.tick_s,
        wind_mps,
        seed,
    )


async def run(args: argparse.Namespace, site: SiteConfig) -> None:
    scenario = load_scenario(CONFIG_DIR, args.scenario)
    seed = scenario.seed if args.seed is None else args.seed
    print_header(scenario, site, seed)
    bus = InProcessBus()
    clock = SimClock(site.simulation.tick_s, pace=None if args.fast else REAL_TIME_PACE)
    printer = asyncio.create_task(print_observations(bus.subscribe(WILDCARD)))
    media = build_media(args, site, scenario.environment.wind_mps, seed)
    truth = await run_scenario(scenario, site, bus, clock, seed=seed, media=media)
    await bus.close()
    await printer
    print_evaluation(summarize(truth))


def main() -> None:
    args = parse_args()
    site = load_site(CONFIG_DIR, zoom_per_station=args.zoom_per_station)
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
