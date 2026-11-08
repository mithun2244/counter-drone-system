"""Paired S3 zoom comparison: the same seeds, inputs and recordings at 0, 1 and 2 zoom cameras.

Recorded media only, because zoom adds look evidence and nothing else. Simulator geometry with
real model output on held-out clips: not real-world performance. Reported, with no target.
Writes ``runs/zoom_comparison/report.md`` and prints the same table.
"""

import argparse
import asyncio
from collections import defaultdict
from pathlib import Path

from cuas.bus import WILDCARD, InProcessBus
from cuas.clock import SimClock
from cuas.config import load_site
from cuas.metrics.alert_evaluator import AlertReport, evaluate_alerts
from cuas.pipeline import start_pipeline
from cuas.schemas import BearingDetection, Message, Track, ZoomTask
from cuas.schemas.topics import ZOOM_TASK
from cuas.sim.engine import run_scenario
from cuas.sim.media import build_media_link
from cuas.sim.scenario import load_scenario
from cuas.sim.truth import TruthLog

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR, DATA_DIR, MODELS_DIR = ROOT / "config", ROOT / "data", ROOT / "models"
OUT_DIR = ROOT / "runs" / "zoom_comparison"
SCENARIO, QUADCOPTER, ZOOMS = "s3", "quad-1", (0, 1, 2)
WIDE = {"rgb", "thermal"}


async def run(seed: int, zoom: int) -> tuple[list[Message], list[Message], TruthLog]:
    site = load_site(CONFIG_DIR, zoom_per_station=zoom)
    scenario = load_scenario(CONFIG_DIR, SCENARIO)
    media = build_media_link(
        CONFIG_DIR,
        DATA_DIR,
        MODELS_DIR,
        OUT_DIR / f"seed{seed}_zoom{zoom}",
        site.station_ai,
        site.simulation.tick_s,
        scenario.environment.wind_mps,
        seed,
    )
    sensor, ingest, control = InProcessBus(), InProcessBus(), InProcessBus()
    clock = SimClock(site.simulation.tick_s)
    taps = [bus.subscribe(WILDCARD) for bus in (sensor, control)]
    zoom_tasks = control.subscribe(ZOOM_TASK)
    labels = scenario.metadata.zone_labels
    pipeline = start_pipeline(sensor, ingest, control, site, labels, lambda: clock.now)
    truth = await run_scenario(
        scenario, site, sensor, clock, seed=seed, media=media, zoom_tasks=zoom_tasks
    )
    await sensor.close()
    await pipeline
    sensed, controlled = [[m async for m in tap] for tap in taps]
    return sensed, controlled, truth


def zoom_looks(sensed: list[Message], truth: TruthLog) -> tuple[int, int, int]:
    """Zoom bearings; those with class evidence; those on a frame a wide camera also showed.

    The simulator logs one truth record per published bearing, in the same order.
    """
    bearings = [m for m in sensed if isinstance(m, BearingDetection)]
    pairs = list(zip(bearings, truth.bearings, strict=True))
    wide_frames: defaultdict[str, set[str]] = defaultdict(set)
    for bearing, real in pairs:
        if bearing.sensor in WIDE and bearing.snapshot_ref:
            wide_frames[real.target_id].add(bearing.snapshot_ref)
    zoom = [(b, real) for b, real in pairs if b.sensor == "zoom"]
    evidence = [(b, real) for b, real in zoom if any(b.class_probs.values())]
    shared = sum(1 for b, real in zoom if b.snapshot_ref in wide_frames[real.target_id])
    return len(zoom), len(evidence), shared


def row(seed: int, zoom: int, report: AlertReport, controlled, looks) -> str:
    red = report.first_red.get(QUADCOPTER)
    to_red = report.time_to_red.get(QUADCOPTER)
    tasks = sum(isinstance(m, ZoomTask) for m in controlled)
    return (
        f"| {seed} | {zoom} | {report.wrong_alerts} | {report.wrong_alarms} | "
        f"{'yes' if red else 'no'} | {'-' if red is None else f'{red[0]:.1f}'} | "
        f"{'-' if to_red is None else f'{to_red:.1f}'} | {tasks} | "
        f"{looks[0]} | {looks[1]} | {looks[2]} |"
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("seeds", type=int, nargs="+")
    seeds = parser.parse_args().seeds
    intro = (
        "Simulator geometry with real model output on held-out recordings. Not real-world "
        "performance. Same seed, scenario and recordings in each row group; only the zoom "
        "cameras per station change. Time to red runs from the first tick wide cameras on two "
        "stations saw the quadcopter (`prd.md` section 8; target 5 s)."
    )
    header = (
        "| Seed | Zoom per station | False alerts | False amber or red assessments | "
        "Quadcopter red | First red, s | Time to red, s | Zoom tasks | Zoom bearings | "
        "With class evidence | Same frame as a wide look |"
    )
    lines = ["# Paired S3 zoom comparison", "", intro, "", header, "|" + " --- |" * 11]
    identical = {}
    for seed in seeds:
        tracks = {}
        for zoom in ZOOMS:
            sensed, controlled, truth = await run(seed, zoom)
            report = evaluate_alerts(truth, controlled)
            tracks[zoom] = [
                m.model_dump_json() for m in controlled if isinstance(m, Track)
            ]
            lines.append(row(seed, zoom, report, controlled, zoom_looks(sensed, truth)))
            print(lines[-1], flush=True)
        identical[seed] = tracks[0] == tracks[1] == tracks[2]
    lines += [
        "",
        "Tracks byte-identical across 0, 1 and 2 zoom cameras: "
        + ", ".join(
            f"seed {s} {'yes' if same else 'NO'}" for s, same in identical.items()
        ),
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(lines[-1])


if __name__ == "__main__":
    asyncio.run(main())
