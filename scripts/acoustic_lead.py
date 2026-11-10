"""Which reports a drone first: a station microphone or a camera? Simulator results, reported only.

Runs a single-target scenario through the pipeline, as ``record_stream.py`` does, and reads only
bus messages, never ground truth. With one target every bearing is that drone's, so the times
below belong to the same drone; scenarios with more than one target are refused. Prints:

- the first station-microphone bearing the gateway accepted (and, with model output, the first
  heard as not background);
- the first frame showing a station-microphone ``pre_alert``: the operator's "Acoustic warning";
- the first camera bearing (``rgb``, ``thermal`` or ``zoom``) the gateway accepted, and, with
  model output, the first the model calls drone. Without model output (no recorded media, or no
  footage of that target type) a camera bearing is the simulated detection only;
- the first confirmed track, alert card, and frame with a linked microphone bearing (the
  "Last heard from" cue), and the leads in seconds.

Usage: uv run python scripts/acoustic_lead.py s5 [--recorded-media] [--seed N] [--json]
"""

import argparse
import asyncio
import json
from pathlib import Path

from cuas.bus import WILDCARD, InProcessBus
from cuas.clock import SimClock
from cuas.config import load_site
from cuas.control.classify import look_probability, sound_probability
from cuas.dashboard.frames import FrameBuilder, replay
from cuas.pipeline import start_pipeline
from cuas.schemas import BearingDetection, Message, Track
from cuas.schemas.topics import GATEWAY_ACCEPTED, ZOOM_TASK
from cuas.sim.engine import run_scenario
from cuas.sim.scenario import load_scenario

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR, DATA_DIR, MODELS_DIR = ROOT / "config", ROOT / "data", ROOT / "models"
SAMPLES_DIR = ROOT / "runs" / "samples"
CAMERAS = ("rgb", "thermal", "zoom")
MICROPHONE = "acoustic"
DECIDED = 0.5  # model output above this share counts as heard (not background) or drone


async def traffic(
    scenario_id: str, recorded_media: bool, seed: int
) -> tuple[list[Message], list[Message]]:
    site = load_site(CONFIG_DIR)
    scenario = load_scenario(CONFIG_DIR, scenario_id)
    media = None
    if recorded_media:
        from cuas.sim.media import build_media_link

        media = build_media_link(
            CONFIG_DIR,
            DATA_DIR,
            MODELS_DIR,
            SAMPLES_DIR / f"lead-{scenario_id}-seed{seed}",
            site.station_ai,
            site.simulation.tick_s,
            scenario.environment.wind_mps,
            seed,
        )
    sensor, ingest, control = InProcessBus(), InProcessBus(), InProcessBus()
    clock = SimClock(site.simulation.tick_s)
    accepted_tap = ingest.subscribe(GATEWAY_ACCEPTED)
    control_tap = control.subscribe(WILDCARD)
    zoom_tasks = control.subscribe(ZOOM_TASK)
    labels = scenario.metadata.zone_labels
    pipeline = start_pipeline(sensor, ingest, control, site, labels, lambda: clock.now)
    await run_scenario(
        scenario, site, sensor, clock, seed=seed, media=media, zoom_tasks=zoom_tasks
    )
    await sensor.close()
    await pipeline
    return [m async for m in accepted_tap], [m async for m in control_tap]


def first_t(items, test) -> float | None:
    return next((round(item.t, 3) for item in items if test(item)), None)


def measure(
    scenario_id: str, recorded_media: bool = False, seed: int | None = None
) -> dict:
    scenario = load_scenario(CONFIG_DIR, scenario_id)
    if len(scenario.targets) != 1:
        raise SystemExit(
            f"{scenario_id} has {len(scenario.targets)} targets: the times could not be "
            "tied to one drone without ground truth"
        )
    seed = scenario.seed if seed is None else seed
    accepted, controlled = asyncio.run(traffic(scenario_id, recorded_media, seed))
    bearings = [m for m in accepted if isinstance(m, BearingDetection)]
    mic = [b for b in bearings if b.sensor == MICROPHONE]
    cam = [b for b in bearings if b.sensor in CAMERAS]
    frames = replay(
        FrameBuilder(scenario_id, load_site(CONFIG_DIR), scenario.metadata.zone_labels),
        accepted,
        controlled,
    )
    out = {
        "scenario": scenario_id,
        "title": scenario.metadata.title,
        "seed": seed,
        "recorded_media": recorded_media,
        "microphone_bearing": first_t(mic, lambda b: True),
        "microphone_heard": first_t(
            mic, lambda b: (sound_probability(b.class_probs) or 0.0) > DECIDED
        ),
        "warning_frame": first_t(
            frames,
            lambda f: any(p.sensor_id.endswith(f".{MICROPHONE}") for p in f.pre_alerts),
        ),
        "camera_bearing": first_t(cam, lambda b: True),
        "camera_drone": first_t(
            cam, lambda b: (look_probability(b.class_probs) or 0.0) > DECIDED
        ),
        "confirmed_track": first_t(
            controlled, lambda m: isinstance(m, Track) and m.status == "confirmed"
        ),
        "alert_frame": first_t(frames, lambda f: f.alerts),
        "last_heard_frame": first_t(
            frames,
            lambda f: any(t.heard and t.status == "confirmed" for t in f.tracks),
        ),
        "clip_frame": first_t(frames, lambda f: any(a.looks for a in f.alerts)),
    }
    if out["camera_bearing"] is not None:
        for lead, start in [
            ("lead_bearing_s", "microphone_bearing"),
            ("lead_warning_s", "warning_frame"),
        ]:
            if out[start] is not None:
                out[lead] = round(out["camera_bearing"] - out[start], 3)
    return out


LABELS = {
    "microphone_bearing": "first station-microphone bearing (accepted)",
    "microphone_heard": "first heard as not background (model output)",
    "warning_frame": 'first frame with the "Acoustic warning" pre-alert',
    "camera_bearing": "first camera bearing (accepted)",
    "camera_drone": "first camera bearing the model calls drone",
    "confirmed_track": "first confirmed track",
    "alert_frame": "first frame with an alert card",
    "last_heard_frame": 'first frame with a "Last heard from" link',
    "clip_frame": "first frame with a camera clip on a card",
    "lead_bearing_s": "lead: camera bearing - microphone bearing (s)",
    "lead_warning_s": "lead: camera bearing - warning frame (s)",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenario")
    parser.add_argument("--recorded-media", action="store_true")
    parser.add_argument("--seed", type=int, help="default: the scenario's own seed")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    out = measure(args.scenario, args.recorded_media, args.seed)
    if args.json:
        print(json.dumps(out))
        return
    print(
        f"Simulator result, not real-world performance. {out['scenario']} "
        f"'{out['title']}', seed {out['seed']}, recorded media {out['recorded_media']}"
    )
    for key, label in LABELS.items():
        value = out.get(key)
        print(f"  {label:50} {'never' if value is None else value}")


if __name__ == "__main__":
    main()
