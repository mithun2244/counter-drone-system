"""Write the dashboard contract's schema, a MOCK edge-state stream, or a sample stream.

``--schema`` writes ``docs/dashboard_contract.schema.json``, ``docs/handoff.schema.json`` and
``docs/basemap.schema.json``. ``--edge-states`` writes
``docs/samples/edge_states.jsonl``: hand-made states the simulator never produces (a sensor
fault, all clear, labelled alerts), marked MOCK. ``--scenario`` runs a scenario as fast as
possible and writes the messages a dashboard would receive, one JSON object per line: ``hello``,
a ``run``, every ``frame`` and the final ``run``. Frames come from the deterministic replay of the
run's accepted observations and control output. No ground truth is written.
"""

import argparse
import asyncio
from pathlib import Path

from cuas.bus import WILDCARD, InProcessBus
from cuas.clock import SimClock
from cuas.config import load_site
from cuas.dashboard.basemap import basemap_schema_text
from cuas.dashboard.contract import (
    AlertCard,
    CoverageView,
    EvidenceEvent,
    EvidenceHead,
    Frame,
    Hello,
    LookRef,
    PicketHeard,
    PreAlert,
    RunInfo,
    SensorView,
    TrackView,
    schema_text,
)
from cuas.dashboard.frames import (
    FrameBuilder,
    profiles,
    replay,
    run_info,
    site_map,
)
from cuas.evidence.handoff import handoff_schema_text
from cuas.media_manifest import dataset_names, load_manifest
from cuas.pipeline import start_pipeline
from cuas.schemas.topics import GATEWAY_ACCEPTED, ZOOM_TASK
from cuas.sim.engine import run_scenario
from cuas.sim.scenario import available_scenarios, load_scenario

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR, DATA_DIR, MODELS_DIR = ROOT / "config", ROOT / "data", ROOT / "models"
SCHEMA_PATH = ROOT / "docs" / "dashboard_contract.schema.json"
HANDOFF_SCHEMA_PATH = ROOT / "docs" / "handoff.schema.json"
BASEMAP_SCHEMA_PATH = ROOT / "docs" / "basemap.schema.json"
EDGE_STATES_PATH = ROOT / "docs" / "samples" / "edge_states.jsonl"
SAMPLES_DIR = ROOT / "runs" / "samples"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--schema", action="store_true", help="write the schema")
    parser.add_argument("--edge-states", action="store_true", help="write the MOCK")
    parser.add_argument("--scenario", choices=available_scenarios(CONFIG_DIR))
    parser.add_argument("--seed", type=int, help="default: the scenario's own seed")
    parser.add_argument("--recorded-media", action="store_true")
    parser.add_argument("--zoom-per-station", type=int, choices=[0, 1, 2])
    parser.add_argument("--out", type=Path, help="default: runs/samples/<id>.jsonl")
    return parser.parse_args()


def all_metadata():
    return [
        load_scenario(CONFIG_DIR, s).metadata for s in available_scenarios(CONFIG_DIR)
    ]


async def record(args: argparse.Namespace, seed: int) -> list[str]:
    site = load_site(CONFIG_DIR, zoom_per_station=args.zoom_per_station)
    scenario = load_scenario(CONFIG_DIR, args.scenario)
    meta = scenario.metadata
    run_id = f"sample-{meta.id}-seed{seed}"
    media = None
    if args.recorded_media:
        from cuas.sim.media import build_media_link

        media = build_media_link(
            CONFIG_DIR,
            DATA_DIR,
            MODELS_DIR,
            SAMPLES_DIR / run_id,
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
    labels = meta.zone_labels
    pipeline = start_pipeline(sensor, ingest, control, site, labels, lambda: clock.now)
    await run_scenario(
        scenario, site, sensor, clock, seed=seed, media=media, zoom_tasks=zoom_tasks
    )
    await sensor.close()
    await pipeline
    accepted = [m async for m in accepted_tap]
    controlled = [m async for m in control_tap]
    known = profiles(all_metadata())
    run = run_info(
        run_id, meta, known, site, seed, scenario.duration_s, media is not None
    )
    datasets = {} if media is None else dataset_names(load_manifest(CONFIG_DIR))
    builder = FrameBuilder(run_id, site, labels, datasets)
    frames = replay(builder, accepted, controlled)
    messages = [
        Hello(profiles=known, run=None, frame=None),
        run,
        *frames,
        run.model_copy(update={"state": "ended", "ended_reason": "completed"}),
    ]
    return [m.model_dump_json() for m in messages]


def sensors(faulty: frozenset[str] = frozenset()) -> list[SensorView]:
    ids = [f"st{n}.{s}" for n in (1, 2, 3) for s in ("acoustic", "rgb", "thermal")]
    ids += [f"pk{n}" for n in range(1, 9)]
    return [
        SensorView(sensor_id=i, ok=i not in faulty, visibility=1.0) for i in sorted(ids)
    ]


def edge_states() -> list[str]:
    """MOCK: hand-made states for UI work, valid by construction. Never real output."""
    site = load_site(CONFIG_DIR)
    meta = load_scenario(CONFIG_DIR, "s2").metadata
    run_id = "mock-edge-states"
    run = RunInfo(
        run_id=run_id,
        profile_id="fictional-stadium",
        scenario_id="s2",
        title="MOCK edge states for UI work",
        venue=meta.venue,
        seed=0,
        duration_s=60.0,
        recorded_media=True,
        zoom_per_station=1,
        state="running",
        speed=1.0,
        site=site_map(site, meta.zone_labels, site.dashboard.map_margin_fraction),
    )
    reach = {"st1": 800.0, "st2": 800.0, "st3": 800.0}
    clear = CoverageView(pct=100.0, warning=False, reach_m=reach)
    reduced = CoverageView(pct=64.0, warning=True, reach_m={**reach, "st2": 0.0})
    trail = [(t, -260.0 - 8.0 * (30.0 - t), 120.0) for t in (24.0, 26.0, 28.0, 30.0)]
    quad = TrackView(
        track_id="trk-1",
        status="confirmed",
        x=-260.0,
        y=120.0,
        z=60.0,
        vx=8.0,
        vy=-3.0,
        n_stations=3,
        coasting=False,
        trail=trail,
        level="red",
        alert_id="alert-1",
        p_drone=0.94,
        p_attack_drone=0.0,
        p_bird=0.06,
    )
    card = AlertCard(
        alert_id="alert-1",
        track_id="trk-1",
        level="red",
        score=0.82,
        tti_s=21.0,
        zone_id="critical",
        zone_label=meta.zone_labels.critical,
        approach="heading_to",
        class_key="drone",
        confidence=0.94,
        n_stations=3,
        coasting=False,
        reasons=[
            "seen hovering",
            "camera look 91% drone",
            "heading to Pitch and Stands, 21 s",
        ],
        label="confirm",
        evidence_records=3,
        looks=[
            LookRef(
                source="st1.rgb", clip_url="/api/clips/st1/0000000000000000", at_s=12.6
            )
        ],
    )
    heard = PreAlert(
        sector_id="sec-1",
        sensor_id="pk4",
        x=2121.3,
        y=-2121.3,
        bearing_deg=315.0,
        compass="NW",
        half_width_deg=20.0,
        first_t=26.0,
        last_t=30.0,
        reports=3,
    )
    head = EvidenceHead(seq=3, record_hash="0" * 64)

    def frame(t: float, **changes: object) -> Frame:
        empty: dict[str, object] = {
            "tracks": [],
            "alerts": [],
            "pre_alerts": [],
            "pickets_heard": [],
            "rays": [],
            "zoom": [],
            "coverage": clear,
            "sensors": sensors(),
            "evidence_head": None,
        }
        return Frame(run_id=run_id, t=t, **{**empty, **changes})

    dismissed = card.model_copy(update={"label": "dismiss", "level": "amber"})
    messages = [
        Hello(profiles=profiles(all_metadata()), run=None, frame=None),
        run,
        frame(10.0),  # all clear: no tracks, an empty queue
        frame(
            20.0,
            sensors=sensors(frozenset({"st2.rgb", "st2.thermal"})),
            coverage=reduced,
        ),
        frame(
            30.0,
            pre_alerts=[heard],
            pickets_heard=[PicketHeard(picket_id="pk4", t=29.0)],
            tracks=[quad],
            alerts=[card],
            evidence_head=head,
        ),
        EvidenceEvent(
            run_id=run_id,
            seq=3,
            kind="label",
            alert_id="alert-1",
            t=30.0,
            record_hash="0" * 64,
        ),
        frame(40.0, tracks=[quad], alerts=[dismissed], evidence_head=head),
        run.model_copy(update={"state": "paused"}),
        run.model_copy(update={"state": "ended", "ended_reason": "completed"}),
    ]
    return [m.model_dump_json() for m in messages]


def write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    print(f"wrote {len(lines)} lines, {path.stat().st_size / 1024:.0f} KB, to {shown}")


def main() -> None:
    args = parse_args()
    if args.schema:
        for path, text in [
            (SCHEMA_PATH, schema_text()),
            (HANDOFF_SCHEMA_PATH, handoff_schema_text()),
            (BASEMAP_SCHEMA_PATH, basemap_schema_text()),
        ]:
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
    elif args.edge_states:
        write(EDGE_STATES_PATH, edge_states())
    elif args.scenario:
        seed = args.seed
        if seed is None:
            seed = load_scenario(CONFIG_DIR, args.scenario).seed
        lines = asyncio.run(record(args, seed))
        write(args.out or SAMPLES_DIR / f"{args.scenario}_seed{seed}.jsonl", lines)
    else:
        raise SystemExit("give --schema, --edge-states or --scenario")


if __name__ == "__main__":
    main()
