"""Mast-bias robustness report: one station's bearings off by a fixed azimuth, S1 and S3.

Baseline simulator runs (no recorded media) on development seeds only, never gate seeds.
Reported, with no target: a real site would calibrate its masts first. Writes
``runs/robustness/mast_bias.md`` and prints the same summary.
"""

import asyncio
from pathlib import Path

from cuas.bus import WILDCARD, InProcessBus
from cuas.clock import SimClock
from cuas.config import load_site
from cuas.metrics.alert_evaluator import AlertReport, evaluate_alerts
from cuas.metrics.track_evaluator import TrackReport, evaluate_tracks
from cuas.pipeline import start_pipeline
from cuas.schemas import Track
from cuas.sim.bias import MastBias
from cuas.sim.engine import run_scenario
from cuas.sim.scenario import load_scenario

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
OUT = ROOT / "runs" / "robustness" / "mast_bias.md"
STATION, BIASES_DEG = "st1", (0.0, 0.2, 0.5)
SEEDS = [s for s in range(1, 20) if s != 7]  # development seeds
ATTACKERS, QUADCOPTER = ("atk-1", "atk-2", "atk-3"), "quad-1"


async def run(
    scenario_id: str, seed: int, bias: float
) -> tuple[TrackReport, AlertReport]:
    site = load_site(CONFIG_DIR)
    scenario = load_scenario(CONFIG_DIR, scenario_id)
    sensor, ingest, control = InProcessBus(), InProcessBus(), InProcessBus()
    clock = SimClock(site.simulation.tick_s)
    tap = control.subscribe(WILDCARD)
    labels = scenario.metadata.zone_labels
    pipeline = start_pipeline(sensor, ingest, control, site, labels, lambda: clock.now)
    truth = await run_scenario(
        scenario, site, MastBias(sensor, STATION, bias), clock, seed=seed
    )
    await sensor.close()
    await pipeline
    controlled = [m async for m in tap]
    tracks = [m for m in controlled if isinstance(m, Track)]
    return evaluate_tracks(truth, tracks), evaluate_alerts(truth, controlled)


def s1_row(seed: int, tracks: TrackReport, alerts: AlertReport) -> str:
    one_red_each = all(
        alerts.alerts_per_target.get(a) == 1 and a in alerts.first_red
        for a in ATTACKERS
    )
    median = "-" if tracks.median_error_m is None else f"{tracks.median_error_m:.2f}"
    worst = "-" if tracks.worst_target is None else f"{tracks.worst_target[1]:.2f}"
    return (
        f"| {seed} | {tracks.confirmed} | {tracks.false_tracks} | {median} | {worst} | "
        f"{'yes' if one_red_each else 'no'} | {alerts.out_of_order_batches} of "
        f"{alerts.red_batches} | {alerts.wrong_alarms} |"
    )


def s3_row(seed: int, tracks: TrackReport, alerts: AlertReport) -> str:
    red = QUADCOPTER in alerts.first_red
    return (
        f"| {seed} | {tracks.false_tracks} | {alerts.wrong_alerts} | {alerts.wrong_alarms} | "
        f"{'yes' if red else 'no'} |"
    )


S1_HEADER = (
    "| Seed | Confirmed tracks | False tracks | Median error, m | Worst target median, m | "
    "One red alert per attack drone | Red batches out of arrival order | "
    "False amber or red assessments |"
)
S3_HEADER = (
    "| Seed | False tracks | False alerts | False amber or red assessments | "
    "Quadcopter red |"
)


async def main() -> None:
    intro = (
        f"Baseline simulator, no recorded media. Station {STATION}'s bearings turned by a fixed "
        f"azimuth. Development seeds {SEEDS[0]}-{SEEDS[-1]} except 7. Reported only."
    )
    lines = ["# Mast-bias robustness", "", intro]
    for bias in BIASES_DEG:
        s1 = [(seed, *await run("s1", seed, bias)) for seed in SEEDS]
        s3 = [(seed, *await run("s3", seed, bias)) for seed in SEEDS]
        exact = sum(1 for _, t, _ in s1 if t.confirmed == 3 and t.false_tracks == 0)
        ordered = sum(1 for _, _, a in s1 if a.out_of_order_batches == 0)
        clean_s3 = sum(1 for _, _, a in s3 if a.wrong_alarms == 0)
        quad_red = sum(1 for _, _, a in s3 if QUADCOPTER in a.first_red)
        summary = (
            f"Bias {bias} deg: S1 exactly 3 tracks and no false track on {exact} of "
            f"{len(SEEDS)}, red order right on {ordered}; S3 no false amber or red on "
            f"{clean_s3} of {len(SEEDS)}, quadcopter red on {quad_red}"
        )
        print(summary, flush=True)
        lines += ["", f"## {bias} deg", "", summary, "", "S1", "", S1_HEADER]
        lines += [
            "|" + " --- |" * 8,
            *(s1_row(*r) for r in s1),
            "",
            "S3",
            "",
            S3_HEADER,
        ]
        lines += ["|" + " --- |" * 5, *(s3_row(*r) for r in s3)]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
