"""Flight paths, fixed before a run starts from each target's own seed."""

import math
from dataclasses import dataclass

import numpy as np

from cuas.config import TargetType
from cuas.sim.rng import stream
from cuas.sim.scenario import BirdFlock, RouteTarget

_TICK_ROUNDING = 1e-9


@dataclass(frozen=True)
class Trajectory:
    """True positions and velocities at clock ticks ``first_tick``, ``first_tick + 1``, ..."""

    target_id: str
    target_type: TargetType
    first_tick: int
    positions: np.ndarray
    velocities: np.ndarray

    def index_at(self, tick: int) -> int | None:
        index = tick - self.first_tick
        return index if 0 <= index < len(self.positions) else None


def build_trajectories(
    spec: RouteTarget | BirdFlock, tick_s: float, duration_s: float
) -> list[Trajectory]:
    """One trajectory per target. A flock of ``count`` birds gives ``count`` trajectories."""
    if isinstance(spec, BirdFlock):
        ticks = _ticks_between(spec.start_s, duration_s, tick_s)
        return [
            _bird(spec, f"{spec.id}-{number:02d}", ticks, tick_s)
            for number in range(1, spec.count + 1)
        ]
    return [_route(spec, tick_s, duration_s)]


def _ticks_between(start_s: float, end_s: float, tick_s: float) -> np.ndarray:
    first = math.ceil(start_s / tick_s - _TICK_ROUNDING)
    last = math.floor(end_s / tick_s + _TICK_ROUNDING)
    return np.arange(first, last + 1)


def _trajectory(
    target_id: str,
    target_type: TargetType,
    ticks: np.ndarray,
    positions: np.ndarray,
    tick_s: float,
) -> Trajectory:
    velocities = (
        np.gradient(positions, tick_s, axis=0)
        if len(positions) > 1
        else np.zeros_like(positions)
    )
    first_tick = int(ticks[0]) if len(ticks) else 0
    return Trajectory(target_id, target_type, first_tick, positions, velocities)


def _route_knots(target: RouteTarget) -> tuple[np.ndarray, np.ndarray]:
    """Times and points where the path changes: waypoint arrivals and the ends of hovers."""
    times = [target.start_s]
    points = [target.waypoints[0].position_enu_m]
    for index, waypoint in enumerate(target.waypoints):
        if index:
            leg_m = math.dist(points[-1], waypoint.position_enu_m)
            times.append(times[-1] + leg_m / target.speed_mps)
            points.append(waypoint.position_enu_m)
        if waypoint.hover_s:
            times.append(times[-1] + waypoint.hover_s)
            points.append(waypoint.position_enu_m)
    return np.array(times), np.array(points)


def _lateral_offsets(target: RouteTarget, times: np.ndarray) -> np.ndarray:
    """Small sideways weave that keeps an attack drone near-straight but not perfectly straight."""
    if target.jitter is None:
        return np.zeros((len(times), 3))
    chord = np.subtract(
        target.waypoints[-1].position_enu_m, target.waypoints[0].position_enu_m
    )
    normal = np.array([-chord[1], chord[0], 0.0]) / math.hypot(chord[0], chord[1])
    phase = stream(target.seed, "path", target.id).uniform(0.0, math.tau)
    cycles = (times - target.start_s) / target.jitter.period_s
    return np.outer(
        target.jitter.amplitude_m * np.sin(math.tau * cycles + phase), normal
    )


def _route(target: RouteTarget, tick_s: float, duration_s: float) -> Trajectory:
    knot_times, knot_points = _route_knots(target)
    ticks = _ticks_between(target.start_s, min(knot_times[-1], duration_s), tick_s)
    times = ticks * tick_s
    positions = np.column_stack(
        [np.interp(times, knot_times, knot_points[:, axis]) for axis in range(3)]
    )
    positions = positions + _lateral_offsets(target, times)
    return _trajectory(target.id, target.type, ticks, positions, tick_s)


def _bird(
    flock: BirdFlock, member_id: str, ticks: np.ndarray, tick_s: float
) -> Trajectory:
    """A curvy wander at steady speed, turning back when it strays too far from home."""
    rng = stream(flock.seed, "bird", member_id)
    home_x, home_y, home_z = flock.home_enu_m
    angle, radius = rng.uniform(0.0, math.tau), flock.spread_m * math.sqrt(rng.random())
    x, y = home_x + radius * math.sin(angle), home_y + radius * math.cos(angle)
    z = home_z + rng.uniform(-flock.altitude_spread_m, flock.altitude_spread_m)
    heading = rng.uniform(0.0, math.tau)
    step_m = rng.uniform(*flock.speed_range_mps) * tick_s
    turn_sigma = math.radians(flock.turn_sigma_deg_per_sqrt_s) * math.sqrt(tick_s)
    turn_back = math.radians(flock.turn_back_deg_per_s) * tick_s

    positions = np.empty((len(ticks), 3))
    for index in range(len(ticks)):
        positions[index] = x, y, z
        heading += rng.normal(0.0, turn_sigma)
        if math.hypot(x - home_x, y - home_y) > flock.roam_radius_m:
            to_home = math.atan2(home_x - x, home_y - y)
            error = (to_home - heading + math.pi) % math.tau - math.pi
            heading += max(-turn_back, min(turn_back, error))
        x += step_m * math.sin(heading)
        y += step_m * math.cos(heading)
    return _trajectory(member_id, flock.type, ticks, positions, tick_s)
