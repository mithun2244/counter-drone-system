import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from cuas.sim.scenario import BirdFlock, RouteTarget, load_scenario
from cuas.sim.trajectories import Trajectory, build_trajectories

TICK = 0.2


def route(**changes: Any) -> RouteTarget:
    values: dict[str, Any] = {
        "id": "t",
        "type": "quadcopter",
        "seed": 1,
        "start_s": 0.0,
        "speed_mps": 50.0,
        "waypoints": [
            {"position_enu_m": (0.0, 0.0, 100.0)},
            {"position_enu_m": (500.0, 0.0, 100.0)},
        ],
    }
    return RouteTarget.model_validate({**values, **changes})


def only(spec: RouteTarget, duration_s: float = 1000.0) -> Trajectory:
    return build_trajectories(spec, TICK, duration_s)[0]


def speeds(trajectory: Trajectory) -> np.ndarray:
    return np.linalg.norm(np.diff(trajectory.positions, axis=0), axis=1) / TICK


def straightness(trajectory: Trajectory) -> float:
    positions = trajectory.positions
    path_m = np.linalg.norm(np.diff(positions, axis=0), axis=1).sum()
    return float(np.linalg.norm(positions[-1] - positions[0]) / path_m)


def test_straight_route_has_known_positions() -> None:
    trajectory = only(route())
    assert trajectory.positions[trajectory.index_at(25)] == pytest.approx(
        [250.0, 0.0, 100.0]
    )
    assert trajectory.positions[-1] == pytest.approx([500.0, 0.0, 100.0])
    assert len(trajectory.positions) == 51  # 10 s at 5 ticks per second, both ends


def test_velocity_is_known_in_mid_route() -> None:
    trajectory = only(route())
    assert trajectory.velocities[20] == pytest.approx([50.0, 0.0, 0.0])


def test_route_starts_at_its_start_time() -> None:
    trajectory = only(route(start_s=5.0))
    assert trajectory.first_tick == 25
    assert trajectory.index_at(24) is None
    assert trajectory.positions[trajectory.index_at(25)] == pytest.approx(
        [0.0, 0.0, 100.0]
    )


def test_route_ends_at_its_last_point() -> None:
    trajectory = only(route())
    assert trajectory.index_at(50) == 50
    assert trajectory.index_at(51) is None


def test_route_stops_at_the_scenario_end() -> None:
    trajectory = only(route(), duration_s=4.0)
    assert len(trajectory.positions) == 21
    assert trajectory.positions[-1] == pytest.approx([200.0, 0.0, 100.0])


def test_target_starting_after_the_scenario_never_appears() -> None:
    trajectory = only(route(start_s=50.0), duration_s=10.0)
    assert len(trajectory.positions) == 0
    assert trajectory.index_at(0) is None


def test_quadcopter_hovers_in_place_for_the_set_time() -> None:
    spec = route(
        speed_mps=10.0,
        waypoints=[
            {"position_enu_m": (0.0, 0.0, 50.0)},
            {"position_enu_m": (100.0, 0.0, 50.0), "hover_s": 4.0},
            {"position_enu_m": (100.0, 100.0, 50.0)},
        ],
    )
    trajectory = only(spec)
    # Arrives at 10 s and leaves at 14 s, which are ticks 50 and 70.
    hover = trajectory.positions[50:71]
    assert np.allclose(hover, [100.0, 0.0, 50.0])
    assert speeds(trajectory)[:50] == pytest.approx(10.0)
    assert speeds(trajectory)[70:] == pytest.approx(10.0)


def test_friendly_drone_uses_the_same_route_model() -> None:
    friendly = only(route(type="friendly_drone"))
    quadcopter = only(route(type="quadcopter"))
    assert friendly.target_type == "friendly_drone"
    assert np.array_equal(friendly.positions, quadcopter.positions)


def s1_trajectories(config_dir: Path) -> list[Trajectory]:
    scenario = load_scenario(config_dir, "s1")
    return [
        t
        for spec in scenario.targets
        for t in build_trajectories(spec, TICK, scenario.duration_s)
    ]


def test_attack_drones_fly_near_straight_at_constant_speed_and_low(
    config_dir: Path,
) -> None:
    for trajectory in s1_trajectories(config_dir):
        assert speeds(trajectory) == pytest.approx(50.0, rel=0.01)
        assert 0.99 <= straightness(trajectory) < 1.0
        altitudes = trajectory.positions[:, 2]
        assert altitudes.min() >= 50.0
        assert altitudes.max() <= 150.0


def test_jitter_is_fixed_by_the_target_seed() -> None:
    jitter = {"amplitude_m": 5.0, "period_s": 20.0}
    same = only(route(jitter=jitter, seed=1))
    assert np.array_equal(same.positions, only(route(jitter=jitter, seed=1)).positions)
    other = only(route(jitter=jitter, seed=2))
    assert not np.array_equal(same.positions, other.positions)


def s3_flock(config_dir: Path) -> BirdFlock:
    return next(
        t for t in load_scenario(config_dir, "s3").targets if isinstance(t, BirdFlock)
    )


def test_each_bird_becomes_its_own_target(config_dir: Path) -> None:
    flock = s3_flock(config_dir)
    birds = build_trajectories(flock, TICK, 90.0)
    assert len(birds) == flock.count
    assert len({bird.target_id for bird in birds}) == flock.count
    assert {bird.target_type for bird in birds} == {"bird"}


def test_birds_wander_at_steady_design_speed_without_hovering(config_dir: Path) -> None:
    for bird in build_trajectories(s3_flock(config_dir), TICK, 90.0):
        assert speeds(bird).min() >= 5.0
        assert speeds(bird).max() <= 20.0
        assert straightness(bird) < 0.8


def test_birds_stay_near_home(config_dir: Path) -> None:
    flock = s3_flock(config_dir)
    # Turning back at the roam radius takes a while, so allow a generous margin past it.
    limit_m = flock.roam_radius_m * 2
    for bird in build_trajectories(flock, TICK, 90.0):
        offsets = bird.positions[:, :2] - np.array(flock.home_enu_m[:2])
        assert np.linalg.norm(offsets, axis=1).max() < limit_m


def test_bird_paths_are_fixed_by_the_flock_seed(config_dir: Path) -> None:
    flock = s3_flock(config_dir)
    first = build_trajectories(flock, TICK, 30.0)
    second = build_trajectories(flock, TICK, 30.0)
    reseeded = build_trajectories(flock.model_copy(update={"seed": 99}), TICK, 30.0)
    for a, b, c in zip(first, second, reseeded, strict=True):
        assert np.array_equal(a.positions, b.positions)
        assert not np.array_equal(a.positions, c.positions)


def test_birds_in_a_flock_do_not_move_in_lockstep(config_dir: Path) -> None:
    birds = build_trajectories(s3_flock(config_dir), TICK, 30.0)
    assert not math.isclose(float(speeds(birds[0])[0]), float(speeds(birds[1])[0]))
    assert not np.array_equal(birds[0].positions, birds[1].positions)
