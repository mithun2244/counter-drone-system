"""The gateway and control layer on real simulator runs. Ground truth is used only to check."""

from collections.abc import AsyncIterator

import pytest

from cuas.bus import WILDCARD, InProcessBus
from cuas.config import SiteConfig, ZoneLabels
from cuas.geometry import bearing_to
from cuas.metrics.track_evaluator import TrackReport, evaluate_tracks
from cuas.pipeline import control_layer, run_control, start_pipeline
from cuas.schemas import (
    BearingDetection,
    CoverageStatus,
    Message,
    RejectedMessage,
    SectorTrack,
    ThreatAssessment,
    Track,
    TrackClass,
    ZoomTask,
)
from cuas.sim.scenario import load_scenario

ALL_SCENARIOS = ["s1", "s2", "s3", "s4"]
TARGET_TYPES = ["attack_drone", "quadcopter", "friendly_drone", "bird"]


def values(item: object) -> list[str]:
    """Every value in a message, without field names: ``p_bird`` is a fixed schema key."""
    if isinstance(item, dict):
        return [v for value in item.values() for v in values(value)]
    if isinstance(item, list | tuple):
        return [v for value in item for v in values(value)]
    return [str(item)]


def tracks_only(messages: list[Message]) -> list[Message]:
    return [m for m in messages if isinstance(m, Track)]


def dumps(messages: list[Message]) -> list[str]:
    return [f"{type(m).__name__} {m.model_dump_json()}" for m in messages]


@pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
async def test_nothing_is_rejected_and_the_simulator_is_untouched(
    record, record_pipeline, scenario_id: str
) -> None:
    alone, _ = await record(scenario_id, seed=7)
    sensed, ingested, _, _ = await record_pipeline(scenario_id, seed=7)
    assert dumps(sensed) == dumps(alone)
    assert not [m for m in ingested if isinstance(m, RejectedMessage)]
    assert dumps(ingested) == dumps(alone)


@pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
async def test_no_control_message_names_a_target(
    record_pipeline, scenario_id: str
) -> None:
    _, ingested, controlled, truth = await record_pipeline(scenario_id, seed=7)
    words = {*TARGET_TYPES, *(state.target_id for state in truth.states)}
    for message in [*ingested, *controlled]:
        text = " ".join(values(message.model_dump()))
        assert not [word for word in words if word in text], text


async def test_only_control_messages_leave_the_control_layer(record_pipeline) -> None:
    _, _, controlled, _ = await record_pipeline("s1", seed=7)
    assert {type(m) for m in controlled} == {
        Track,
        SectorTrack,
        TrackClass,
        ThreatAssessment,
        ZoomTask,
        CoverageStatus,
    }


async def test_heard_but_never_seen_gives_wedges_and_no_3d_position(
    record_pipeline, config_dir
) -> None:
    s1 = load_scenario(config_dir, "s1")
    blind = s1.model_copy(
        update={
            "environment": s1.environment.model_copy(update={"visibility_factor": 0.0})
        }
    )
    sensed, _, controlled, _ = await record_pipeline(blind, seed=7)
    assert not [
        m for m in sensed if isinstance(m, BearingDetection) and m.sensor != "acoustic"
    ]
    assert not [m for m in controlled if isinstance(m, Track)]
    assert [m for m in controlled if isinstance(m, SectorTrack)]


async def test_a_message_the_gateway_rejects_never_reaches_the_tracker(
    site: SiteConfig,
) -> None:
    """A bearing from far in the future would move the tracker's clock if it got through."""
    sensor, ingest, control = InProcessBus(), InProcessBus(), InProcessBus()
    output = control.subscribe(WILDCARD)
    labels = ZoneLabels(critical="c", important="i", perimeter="p")
    pipeline = start_pipeline(sensor, ingest, control, site, labels, lambda: 0.0)
    target = (300.0, 900.0, 80.0)
    for t in (0.0, 0.2, 0.4, 1000.0):
        for station in site.stations:
            azimuth, elevation, _ = bearing_to(station.position_enu_m, target)
            await sensor.publish(
                "station.bearing",
                BearingDetection(
                    station_id=station.id,
                    sensor="rgb",
                    t=t,
                    azimuth_deg=azimuth,
                    elevation_deg=elevation,
                    sigma_deg=0.05,
                ),
            )
    await sensor.close()
    await pipeline
    times = [m.t async for m in output]
    assert times  # the valid bearings did make a track
    assert max(times) < 1000.0


async def replay(messages: list[Message]) -> AsyncIterator[Message]:
    for message in messages:
        yield message


async def test_replaying_the_accepted_messages_alone_gives_the_same_tracks(
    record_pipeline, site: SiteConfig, config_dir
) -> None:
    """With no simulator in the process, the same input gives the same output."""
    _, ingested, live, _ = await record_pipeline("s1", seed=7)
    accepted = [m for m in ingested if not isinstance(m, RejectedMessage)]
    sink = InProcessBus()
    tap = sink.subscribe(WILDCARD)
    labels = load_scenario(config_dir, "s1").metadata.zone_labels
    await run_control(control_layer(site, labels), replay(accepted), sink)
    await sink.close()
    assert dumps([m async for m in tap]) == dumps(live)


async def test_class_data_never_changes_the_tracks(
    record_pipeline, site: SiteConfig, config_dir
) -> None:
    """Made-up class scores and snapshots on every bearing must leave the tracks unchanged."""
    _, ingested, live, _ = await record_pipeline("s1", seed=7)
    accepted = [m for m in ingested if not isinstance(m, RejectedMessage)]
    labelled = [
        m.model_copy(
            update={
                "class_probs": {"drone": (i % 10) / 10, "bird": 1.0},
                "snapshot_ref": f"abcd:{i}",
            }
        )
        if isinstance(m, BearingDetection)
        else m
        for i, m in enumerate(accepted)
    ]
    sink = InProcessBus()
    tap = sink.subscribe(WILDCARD)
    labels = load_scenario(config_dir, "s1").metadata.zone_labels
    await run_control(control_layer(site, labels), replay(labelled), sink)
    await sink.close()
    replayed = [m async for m in tap]
    assert dumps(tracks_only(replayed)) == dumps(tracks_only(live))


async def test_target_order_leaves_no_trace_in_the_tracks(
    record_pipeline, config_dir
) -> None:
    scenario = load_scenario(config_dir, "s1")
    flipped = scenario.model_copy(update={"targets": tuple(reversed(scenario.targets))})
    _, _, original, _ = await record_pipeline(scenario)
    _, _, reordered, _ = await record_pipeline(flipped)
    assert dumps(original) == dumps(reordered)


async def test_same_seed_same_tracks_and_pace_does_not_matter(record_pipeline) -> None:
    _, _, first, _ = await record_pipeline("s2", seed=7)
    _, _, second, _ = await record_pipeline("s2", seed=7)
    _, _, paced, _ = await record_pipeline("s2", seed=7, pace=100.0)
    assert first
    assert dumps(first) == dumps(second) == dumps(paced)


MAX_MEDIAN_ERROR_M = 20.0  # phases.md, Phase 3
# The scenario's own seed, seed 7, and 20 seeds the design prototype never ran.
ACCEPTANCE_SEEDS = [None, 7, *range(101, 121)]


async def track_report(
    record_pipeline, scenario_id: str, seed: int | None
) -> TrackReport:
    _, _, controlled, truth = await record_pipeline(scenario_id, seed=seed)
    return evaluate_tracks(truth, [m for m in controlled if isinstance(m, Track)])


def assert_accurate(report: TrackReport) -> None:
    assert report.median_error_m is not None
    assert report.median_error_m <= MAX_MEDIAN_ERROR_M
    assert report.worst_target[1] <= MAX_MEDIAN_ERROR_M


@pytest.mark.parametrize("seed", ACCEPTANCE_SEEDS, ids=str)
async def test_s1_exactly_three_confirmed_tracks_within_20_m(
    record_pipeline, seed: int | None
) -> None:
    report = await track_report(record_pipeline, "s1", seed)
    assert report.confirmed == 3
    assert report.false_tracks == 0
    assert report.overlapping_duplicates == report.sequential_duplicates == 0
    assert report.tracks_per_target == {"atk-1": 1, "atk-2": 1, "atk-3": 1}
    assert_accurate(report)


@pytest.mark.parametrize("seed", ACCEPTANCE_SEEDS, ids=str)
async def test_s2_median_error_within_20_m(record_pipeline, seed: int | None) -> None:
    report = await track_report(record_pipeline, "s2", seed)
    assert report.drones_tracked == (1, 1)
    assert_accurate(report)
