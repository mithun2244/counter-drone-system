"""Hand-calculated cases for the constant-velocity filter."""

import numpy as np
import pytest

from cuas.control.kalman import State, predict, start, update

I3 = np.eye(3)


def at_rest(position_var: float, speed_var: float) -> State:
    return start(np.zeros(3), I3 * position_var, speed_var**0.5)


def test_start_is_at_rest_with_the_given_uncertainty() -> None:
    state = start(np.array([1.0, 2.0, 3.0]), I3 * 4.0, 60.0)
    assert list(state.mean) == [1.0, 2.0, 3.0, 0.0, 0.0, 0.0]
    assert np.diag(state.covariance).tolist() == [4.0, 4.0, 4.0, 3600.0, 3600.0, 3600.0]


def test_predict_moves_at_constant_velocity() -> None:
    state = State(np.array([0.0, 0.0, 100.0, 10.0, -5.0, 1.0]), np.zeros((6, 6)))
    moved = predict(state, 2.0, 0.0)
    assert list(moved.position) == [20.0, -10.0, 102.0]
    assert list(moved.velocity) == [10.0, -5.0, 1.0]


def test_predict_adds_white_noise_acceleration() -> None:
    """For dt = 1 and sigma = 1, each axis gains [[1/4, 1/2], [1/2, 1]]."""
    noise = predict(State(np.zeros(6), np.zeros((6, 6))), 1.0, 1.0).covariance
    assert noise[0, 0] == pytest.approx(0.25)
    assert noise[0, 3] == noise[3, 0] == pytest.approx(0.5)
    assert noise[3, 3] == pytest.approx(1.0)
    assert noise[0, 1] == 0.0


def test_predict_by_zero_seconds_changes_nothing() -> None:
    state = at_rest(4.0, 9.0)
    assert predict(state, 0.0, 15.0) is state


def test_an_equally_certain_measurement_lands_halfway() -> None:
    state = update(at_rest(4.0, 9.0), np.array([2.0, -4.0, 6.0]), I3 * 4.0)
    assert list(state.position) == pytest.approx([1.0, -2.0, 3.0])
    assert np.diag(state.covariance)[:3].tolist() == pytest.approx([2.0, 2.0, 2.0])
    assert list(state.velocity) == [0.0, 0.0, 0.0]  # no position-velocity coupling yet


def test_repeated_fixes_learn_the_velocity() -> None:
    true_velocity = np.array([50.0, -20.0, 0.0])
    state = start(np.zeros(3), I3, 60.0)
    for step in range(1, 30):
        state = predict(state, 0.2, 15.0)
        state = update(state, true_velocity * 0.2 * step, I3 * 0.01)
    assert list(state.velocity) == pytest.approx(list(true_velocity), abs=0.5)


def test_covariance_stays_symmetric_and_positive() -> None:
    state = start(np.zeros(3), I3 * 25.0, 60.0)
    rng = np.random.default_rng(0)
    for _ in range(200):
        state = predict(state, 0.2, 15.0)
        state = update(state, rng.normal(0.0, 1.0, 3), I3 * rng.uniform(0.1, 10.0))
    assert np.array_equal(state.covariance, state.covariance.T)
    assert np.linalg.eigvalsh(state.covariance).min() > 0.0
