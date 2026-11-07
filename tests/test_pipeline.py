"""The gateway and control layer on real simulator runs. Ground truth is used only to check."""

from collections.abc import AsyncIterator

import pytest

from cuas.bus import WILDCARD, InProcessBus
from cuas.config import SiteConfig
from cuas.geometry import bearing_to
from cuas.pipeline import control_layer, run_control, start_pipeline
from cuas.schemas import (
    BearingDetection,
    Message,
    RejectedMessage,
    SectorTrack,
    Track,
)
from cuas.sim.scenario import load_scenario

ALL_SCENARIOS = ["s1", "s2", "s3", "s4"]
TARGET_TYPES = ["attack_drone", "quadcopter", "friendly_drone", "bird"]


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
        text = message.model_dump_json()
        assert not [word for word in words if word in text], text


async def test_only_tracks_and_sectors_leave_the_control_layer(record_pipeline) -> None:
    _, _, controlled, _ = await record_pipeline("s1", seed=7)
    assert {type(m) for m in controlled} == {Track, SectorTrack}


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
    pipeline = start_pipeline(sensor, ingest, control, site, lambda: 0.0)
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
    record_pipeline, site: SiteConfig
) -> None:
    """With no simulator in the process, the same input gives the same output."""
    _, ingested, live, _ = await record_pipeline("s1", seed=7)
    accepted = [m for m in ingested if not isinstance(m, RejectedMessage)]
    sink = InProcessBus()
    tap = sink.subscribe(WILDCARD)
    await run_control(control_layer(site), replay(accepted), sink)
    await sink.close()
    assert dumps([m async for m in tap]) == dumps(live)


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
