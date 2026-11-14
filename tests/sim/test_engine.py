import asyncio
import math
from pathlib import Path

import pytest

from cuas.bus import WILDCARD, InProcessBus
from cuas.clock import SimClock
from cuas.config import SiteConfig
from cuas.geometry import angle_difference_deg
from cuas.schemas import BearingDetection, Message, PicketAlert, SensorStatus
from cuas.sim.engine import run_scenario
from cuas.sim.scenario import Environment, Scenario, load_scenario
from cuas.sim.station import in_field_of_view
from cuas.sim.trajectories import build_trajectories

ALL_SCENARIOS = ["s1", "s2", "s3", "s4", "s5"]
NOISE_LIMIT_SIGMAS = 6.0


def bearings_in(messages: list[Message]) -> list[BearingDetection]:
    return [m for m in messages if isinstance(m, BearingDetection)]


def alerts_in(messages: list[Message]) -> list[PicketAlert]:
    return [m for m in messages if isinstance(m, PicketAlert)]


def range_factor(sensor: str, environment: Environment, site: SiteConfig) -> float:
    if sensor == "acoustic":
        return environment.wind_range_factor(site.simulation)
    return environment.visibility_factor


@pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
async def test_every_detection_is_inside_range_view_and_elevation_limits(
    record, site: SiteConfig, config_dir: Path, scenario_id: str
) -> None:
    environment = load_scenario(config_dir, scenario_id).environment
    _, truth = await record(scenario_id, seed=7)
    assert truth.bearings
    for bearing in truth.bearings:
        settings = site.sensors[bearing.sensor]
        expected_range = settings.base_range_m[bearing.target_type] * range_factor(
            bearing.sensor, environment, site
        )
        assert bearing.max_range_m == expected_range
        assert bearing.range_m < bearing.max_range_m
        assert in_field_of_view(bearing.azimuth_deg, bearing.elevation_deg, settings)


@pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
async def test_each_bearing_lines_up_with_its_truth_within_noise(
    record, scenario_id: str
) -> None:
    messages, truth = await record(scenario_id, seed=7)
    bearings = bearings_in(messages)
    assert len(bearings) == len(truth.bearings)
    for bearing, real in zip(bearings, truth.bearings, strict=True):
        assert (bearing.t, bearing.station_id, bearing.sensor) == (
            real.t,
            real.station_id,
            real.sensor,
        )
        limit = NOISE_LIMIT_SIGMAS * bearing.sigma_deg
        assert abs(angle_difference_deg(bearing.azimuth_deg, real.azimuth_deg)) <= limit
        assert abs(bearing.elevation_deg - real.elevation_deg) <= limit


@pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
async def test_every_alert_is_inside_its_hearing_radius(
    record, scenario_id: str
) -> None:
    messages, truth = await record(scenario_id, seed=7)
    assert len(alerts_in(messages)) == len(truth.picket_alerts)
    for alert in truth.picket_alerts:
        assert alert.distance_m <= alert.hearing_radius_m


@pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
async def test_every_sensor_reports_status_each_second(
    record, site: SiteConfig, config_dir: Path, scenario_id: str
) -> None:
    duration_s = load_scenario(config_dir, scenario_id).duration_s
    messages, _ = await record(scenario_id, seed=7)
    statuses = [m for m in messages if isinstance(m, SensorStatus)]
    sensors = len(site.stations) * len(site.sensors) + len(site.pickets)
    assert len(statuses) == sensors * (int(duration_s) + 1)
    assert len({s.sensor_id for s in statuses}) == sensors


@pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
async def test_the_run_ends_on_time(record, config_dir: Path, scenario_id: str) -> None:
    duration_s = load_scenario(config_dir, scenario_id).duration_s
    messages, _ = await record(scenario_id, seed=7)
    assert max(m.t for m in messages) == pytest.approx(duration_s)


@pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
def test_target_ids_are_unique(config_dir: Path, scenario_id: str) -> None:
    scenario = load_scenario(config_dir, scenario_id)
    ids = [
        trajectory.target_id
        for spec in scenario.targets
        for trajectory in build_trajectories(spec, 0.2, scenario.duration_s)
    ]
    assert len(ids) == len(set(ids))


async def test_truth_holds_one_state_per_active_target_per_tick(record) -> None:
    _, truth = await record("s2", seed=7)
    times = [state.t for state in truth.states]
    assert len(times) == len(set(times))
    assert {state.target_id for state in truth.states} == {"quad-1"}


async def test_seed_defaults_to_the_scenario_seed(record) -> None:
    default, _ = await record("s2")
    explicit, _ = await record("s2", seed=2002)
    assert [m.model_dump_json() for m in default] == [
        m.model_dump_json() for m in explicit
    ]


async def test_a_used_clock_is_refused(site: SiteConfig, config_dir: Path) -> None:
    clock = SimClock(site.simulation.tick_s)
    await clock.tick()
    scenario: Scenario = load_scenario(config_dir, "s2")
    with pytest.raises(ValueError, match="fresh clock"):
        await run_scenario(scenario, site, InProcessBus(), clock)


async def test_s1_is_heard_by_pickets_before_any_station_sees_it(record) -> None:
    messages, _ = await record("s1")
    bearings, alerts = bearings_in(messages), alerts_in(messages)
    assert {b.station_id for b in bearings} == {"st1", "st2", "st3"}
    assert alerts
    assert min(a.t for a in alerts) < min(b.t for b in bearings)


async def test_s1_drones_all_reach_the_site_centre(
    record, site: SiteConfig, config_dir: Path
) -> None:
    _, truth = await record("s1")
    last = {state.target_id: state for state in truth.states}
    assert set(last) == {"atk-1", "atk-2", "atk-3"}
    for target in load_scenario(config_dir, "s1").targets:
        # The last tick can fall up to one tick of flight short of the end, and the sideways
        # weave is at right angles to that.
        one_tick_m = target.speed_mps * site.simulation.tick_s
        limit_m = math.hypot(one_tick_m, target.jitter.amplitude_m)
        x, y, _ = last[target.id].position_enu_m
        assert math.hypot(x, y) <= limit_m


async def test_s2_quadcopter_is_seen_by_all_stations_and_too_quiet_for_pickets(
    record,
) -> None:
    messages, _ = await record("s2")
    assert {b.station_id for b in bearings_in(messages)} == {"st1", "st2", "st3"}
    assert not alerts_in(messages)


async def test_s3_birds_are_seen_so_later_phases_have_something_to_reject(
    record,
) -> None:
    messages, truth = await record("s3")
    bird_bearings = [b for b in truth.bearings if b.target_type == "bird"]
    assert bird_bearings
    assert {b.sensor for b in bird_bearings} == {"rgb", "thermal"}
    assert not alerts_in(messages)


async def test_a_stopped_clock_ends_the_run_early(
    site: SiteConfig, config_dir: Path
) -> None:
    scenario = load_scenario(config_dir, "s2")
    clock = SimClock(site.simulation.tick_s)
    bus = InProcessBus()
    heard = bus.subscribe(WILDCARD)

    async def stop_at_five_seconds() -> None:
        async for message in heard:
            if message.t >= 5.0:
                clock.stop()
                return

    stopper = asyncio.create_task(stop_at_five_seconds())
    await asyncio.wait_for(run_scenario(scenario, site, bus, clock), 60)
    await asyncio.wait_for(stopper, 1)
    assert clock.stopped and 5.0 <= clock.now < 6.0 < scenario.duration_s
