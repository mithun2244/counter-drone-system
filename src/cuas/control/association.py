"""Bearing-to-track association (docs/design.md A6).

A bearing matches a track if it lies within ``gate_sigmas`` of the bearing the track predicts.
The sigma combines the bearing's own noise with the track's position uncertainty seen from the
station, because a moving target is never exactly where the filter expects.
"""

import math

import numpy as np
from scipy.optimize import linear_sum_assignment

from cuas.geometry import angle_difference_deg, bearing_to
from cuas.schemas import BearingDetection

DEG_PER_RAD = math.degrees(1.0)
NO_MATCH = 1e12  # cost of a pair outside the gate; never chosen over one inside it
MIN_RANGE_M = 1.0  # a track on top of a station has no defined bearing


def bearing_distance2(
    position: np.ndarray,
    position_covariance: np.ndarray,
    origin: np.ndarray,
    bearing: BearingDetection,
) -> float:
    """Squared Mahalanobis distance, in sigmas, between a bearing and the track's bearing."""
    expected_az, expected_el, range_m = bearing_to(origin, position)
    if range_m < MIN_RANGE_M:
        return math.inf
    az, el = math.radians(expected_az), math.radians(expected_el)
    across = np.array([math.cos(az), -math.sin(az), 0.0])
    up = np.array(
        [-math.sin(az) * math.sin(el), -math.cos(az) * math.sin(el), math.cos(el)]
    )
    jacobian = np.vstack([across, up]) * DEG_PER_RAD / range_m
    innovation = np.array(
        [
            angle_difference_deg(bearing.azimuth_deg, expected_az) * math.cos(el),
            bearing.elevation_deg - expected_el,
        ]
    )
    spread = (
        jacobian @ position_covariance @ jacobian.T + np.eye(2) * bearing.sigma_deg**2
    )
    return float(innovation @ np.linalg.solve(spread, innovation))


def assign(distances2: np.ndarray, gate_sigmas: float) -> list[tuple[int, int]]:
    """One-to-one (row, column) pairs with the least total distance, every pair inside the gate."""
    if distances2.size == 0:
        return []
    inside = distances2 <= gate_sigmas**2
    rows, columns = linear_sum_assignment(np.where(inside, distances2, NO_MATCH))
    return [
        (int(r), int(c)) for r, c in zip(rows, columns, strict=True) if inside[r, c]
    ]
