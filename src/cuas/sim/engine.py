"""The tick loop: moves the targets, runs the sensor models and publishes what they report."""

import asyncio
import contextlib
from collections.abc import AsyncIterator

from cuas.bus import Bus
from cuas.clock import SimClock
from cuas.config import SiteConfig
from cuas.schemas import Message, ZoomTask
from cuas.schemas.topics import BEARING_DETECTION, PICKET_ALERT, SENSOR_STATUS
from cuas.sim.picket import PicketSim
from cuas.sim.scenario import Scenario
from cuas.sim.station import LookSource, Observation, StationSim
from cuas.sim.trajectories import Trajectory, build_trajectories
from cuas.sim.truth import TargetState, TruthLog
from cuas.sim.zoom import ZoomSim

# ponytail: settles by yielding, which is enough because in-process stages never suspend in the
# middle of a message: sensor bus -> gateway -> control layer -> zoom intake is three hops. A
# network bus needs an explicit acknowledgement instead.
SETTLE_YIELDS = 4


async def run_scenario(
    scenario: Scenario,
    site: SiteConfig,
    bus: Bus,
    clock: SimClock,
    seed: int | None = None,
    media: LookSource | None = None,
    zoom_tasks: AsyncIterator[Message] | None = None,
) -> TruthLog:
    """Run to the end. Observations go on the bus; ground truth is only ever returned.

    With recorded media, ``zoom_tasks`` points the zoom cameras. Each tick then waits for the
    pipeline to settle, so the tasks a tick sees never depend on how fast anything ran.
    """
    if clock.now != 0.0:
        raise ValueError("run_scenario needs a fresh clock")
    clock.start()
    run_seed = scenario.seed if seed is None else seed
    wind_factor = scenario.environment.wind_range_factor(site.simulation)
    stations = [
        StationSim(station, site, scenario.environment, run_seed, media)
        for station in site.stations
    ]
    pickets = [
        PicketSim(
            picket, site.picket_settings, clock.tick_s, wind_factor, run_seed, media
        )
        for picket in site.pickets
    ]
    trajectories = [
        trajectory
        for spec in scenario.targets
        for trajectory in build_trajectories(spec, clock.tick_s, scenario.duration_s)
    ]
    status_every_ticks = round(site.simulation.status_period_s / clock.tick_s)
    last_tick = round(scenario.duration_s / clock.tick_s)
    truth = TruthLog()
    zoom, intake = None, None
    if media is not None and zoom_tasks is not None:
        zoom = ZoomSim(site, scenario.environment, run_seed, media)
        intake = asyncio.create_task(_take_tasks(zoom_tasks, zoom))
    for tick in range(last_tick + 1):
        t = clock.now
        if zoom is not None:
            for _ in range(SETTLE_YIELDS):
                await asyncio.sleep(0)
            zoom.point(t)
        if tick % status_every_ticks == 0:
            await _publish_statuses(bus, stations, pickets, t)
        observations = _sense_targets(
            trajectories, stations, pickets, zoom, tick, t, truth
        )
        await _publish_bearings(bus, observations, truth)
        await _publish_alerts(bus, pickets, tick, t, truth)
        if tick < last_tick:
            await clock.tick()
    if intake is not None:
        intake.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await intake
    return truth


async def _take_tasks(tasks: AsyncIterator[Message], zoom: ZoomSim) -> None:
    async for task in tasks:
        if isinstance(task, ZoomTask):
            zoom.task(task)


async def _publish_statuses(
    bus: Bus, stations: list[StationSim], pickets: list[PicketSim], t: float
) -> None:
    for station in stations:
        for status in station.statuses(t):
            await bus.publish(SENSOR_STATUS, status)
    for picket in pickets:
        await bus.publish(SENSOR_STATUS, picket.status(t))


def _sense_targets(
    trajectories: list[Trajectory],
    stations: list[StationSim],
    pickets: list[PicketSim],
    zoom: ZoomSim | None,
    tick: int,
    t: float,
    truth: TruthLog,
) -> list[Observation]:
    """Log where each active target truly is, and let every sensor try to pick it up."""
    observations: list[Observation] = []
    for trajectory in trajectories:
        index = trajectory.index_at(tick)
        if index is None:
            continue
        position = trajectory.positions[index].tolist()
        target_id, target_type = trajectory.target_id, trajectory.target_type
        truth.states.append(
            TargetState(
                t=t,
                target_id=target_id,
                target_type=target_type,
                position_enu_m=tuple(position),
                velocity_mps=tuple(trajectory.velocities[index].tolist()),
            )
        )
        for station in stations:
            observations.extend(station.observe(target_id, target_type, position, t))
        if zoom is not None:
            observations.extend(zoom.observe(target_id, target_type, position, t))
        for picket in pickets:
            picket.listen(target_id, target_type, position, tick, t)
    return observations


async def _publish_bearings(
    bus: Bus, observations: list[Observation], truth: TruthLog
) -> None:
    """Sorted by sensor and noisy bearing, so the order cannot reveal which target is which."""
    observations.sort(
        key=lambda o: (
            o[0].station_id,
            o[0].sensor,
            o[0].azimuth_deg,
            o[0].elevation_deg,
        )
    )
    for bearing, bearing_truth in observations:
        truth.bearings.append(bearing_truth)
        await bus.publish(BEARING_DETECTION, bearing)


async def _publish_alerts(
    bus: Bus, pickets: list[PicketSim], tick: int, t: float, truth: TruthLog
) -> None:
    """Sorted for the same reason as bearings."""
    reports = [report for picket in pickets for report in picket.due(tick, t)]
    reports.sort(key=lambda r: (r[0].picket_id, r[0].bearing_deg, r[0].loudness))
    for alert, alert_truth in reports:
        truth.picket_alerts.append(alert_truth)
        await bus.publish(PICKET_ALERT, alert)
