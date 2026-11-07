"""Constant-velocity Kalman filter on 3D position (docs/design.md A6).

The state is ``[x, y, z, vx, vy, vz]``, and only position is measured. A bearing-level EKF is a
later upgrade.
"""

from dataclasses import dataclass

import numpy as np

IDENTITY_3 = np.eye(3)
MEASURES_POSITION = np.hstack([IDENTITY_3, np.zeros((3, 3))])


@dataclass(frozen=True)
class State:
    mean: np.ndarray
    covariance: np.ndarray

    @property
    def position(self) -> np.ndarray:
        return self.mean[:3]

    @property
    def velocity(self) -> np.ndarray:
        return self.mean[3:]


def start(position: np.ndarray, covariance: np.ndarray, speed_sigma: float) -> State:
    """At rest, as sure of position as the first fix, and unsure of velocity."""
    mean = np.concatenate([position, np.zeros(3)])
    full = np.zeros((6, 6))
    full[:3, :3] = covariance
    full[3:, 3:] = IDENTITY_3 * speed_sigma**2
    return State(mean, full)


def predict(state: State, dt: float, accel_sigma: float) -> State:
    """Move on by ``dt`` seconds, with white-noise acceleration of ``accel_sigma``."""
    if dt == 0.0:
        return state
    move = np.eye(6)
    move[:3, 3:] = IDENTITY_3 * dt
    variance = accel_sigma**2
    noise = np.block(
        [
            [IDENTITY_3 * variance * dt**4 / 4, IDENTITY_3 * variance * dt**3 / 2],
            [IDENTITY_3 * variance * dt**3 / 2, IDENTITY_3 * variance * dt**2],
        ]
    )
    return State(move @ state.mean, move @ state.covariance @ move.T + noise)


def update(state: State, position: np.ndarray, covariance: np.ndarray) -> State:
    """Blend in a measured position with its covariance."""
    innovation = state.covariance[:3, :3] + covariance
    gain = state.covariance @ MEASURES_POSITION.T @ np.linalg.inv(innovation)
    mean = state.mean + gain @ (position - state.position)
    updated = (np.eye(6) - gain @ MEASURES_POSITION) @ state.covariance
    return State(mean, (updated + updated.T) / 2)
