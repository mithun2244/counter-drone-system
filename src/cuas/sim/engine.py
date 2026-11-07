"""The tick loop: moves the targets, runs the sensor models and publishes what they report."""

from cuas.bus import Bus
from cuas.clock import SimClock
from cuas.config import SiteConfig
from cuas.schemas.topics import BEARING_DETECTION, PICKET_ALERT, SENSOR_STATUS
from cuas.sim.picket import PicketSim
from cuas.sim.scenario import Scenario
from cuas.sim.station import LookSource, Observation, StationSim
from cuas.sim.trajectories import Trajectory, build_trajectories
from cuas.sim.truth import TargetState, TruthLog


async def run_scenario(
    scenario: Scenario,
    site: SiteConfig,
    bus: Bus,
    clock: SimClock,
    seed: int | None = None,
    media: LookSource | None = None,
) -> TruthLog:
    """Run to the end. Observations go on the bus; ground truth is only ever returned."""
    if clock.now != 0.0:
        raise ValueError("run_scenario needs a fresh clock")
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
    for tick in range(last_tick + 1):
        t = clock.now
        if tick % status_every_ticks == 0:
            await _publish_statuses(bus, stations, pickets, t)
        observations = _sense_targets(trajectories, stations, pickets, tick, t, truth)
        await _publish_bearings(bus, observations, truth)
        await _publish_alerts(bus, pickets, tick, t, truth)
        if tick < last_tick:
            await clock.tick()
    return truth


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
