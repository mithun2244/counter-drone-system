import math

import numpy as np
import pytest

from cuas.control.association import assign, bearing_distance2
from cuas.geometry import bearing_to, wrap_azimuth
from cuas.schemas import BearingDetection

ORIGIN = np.array([0.0, 0.0, 0.0])
SIGMA = 0.05
SURE = np.zeros((3, 3))


def bearing(azimuth: float, elevation: float, sigma: float = SIGMA) -> BearingDetection:
    return BearingDetection(
        station_id="st1",
        sensor="rgb",
        t=0.0,
        azimuth_deg=wrap_azimuth(azimuth),
        elevation_deg=elevation,
        sigma_deg=sigma,
    )


def toward(position: np.ndarray, d_azimuth: float = 0.0) -> BearingDetection:
    azimuth, elevation, _ = bearing_to(ORIGIN, position)
    return bearing(azimuth + d_azimuth, elevation)


def test_a_bearing_straight_at_the_track_is_zero_sigmas_away() -> None:
    position = np.array([300.0, 900.0, 80.0])
    assert bearing_distance2(position, SURE, ORIGIN, toward(position)) == pytest.approx(
        0.0
    )


@pytest.mark.parametrize("elevation", [0.0, 60.0])
def test_three_sigmas_of_azimuth_is_nine(elevation: float) -> None:
    """An azimuth error spans less sky at high elevation, so it is scaled by cos(el)."""
    position = np.array([0.0, 1000.0, 1000.0 * math.tan(math.radians(elevation))])
    offset = 3 * SIGMA / math.cos(math.radians(elevation))
    distance2 = bearing_distance2(position, SURE, ORIGIN, toward(position, offset))
    assert distance2 == pytest.approx(9.0, rel=1e-3)


def test_track_uncertainty_widens_the_gate() -> None:
    """At 1 km, 10 bearing sigmas is 8.7 m: outside for a sure track, inside for an unsure one."""
    position = np.array([0.0, 1000.0, 0.0])
    off = toward(position, 10 * SIGMA)
    assert bearing_distance2(position, SURE, ORIGIN, off) > 9.0
    assert bearing_distance2(position, np.eye(3) * 25.0, ORIGIN, off) < 9.0


def test_azimuth_wraps_across_north() -> None:
    position = np.array([-1.0, 1000.0, 0.0])  # just west of north, at 359.94 degrees
    assert bearing_distance2(position, SURE, ORIGIN, bearing(0.01, 0.0)) < 9.0


def test_a_track_on_top_of_the_station_matches_nothing() -> None:
    assert bearing_distance2(ORIGIN, SURE, ORIGIN, bearing(0.0, 0.0)) == math.inf


def test_assignment_minimises_the_total_not_each_pick() -> None:
    """Greedy would take the 1 first and be left with 8; the best total is 2 + 2."""
    distances2 = np.array([[1.0, 2.0], [2.0, 8.0]])
    assert sorted(assign(distances2, 3.0)) == [(0, 1), (1, 0)]


def test_nothing_outside_the_gate_is_paired_even_if_it_is_the_only_choice() -> None:
    distances2 = np.array([[1.0, 50.0], [math.inf, 12.0]])
    assert assign(distances2, 3.0) == [(0, 0)]


def test_more_bearings_than_tracks_and_no_tracks_at_all() -> None:
    assert assign(np.array([[4.0, 0.5, 9.5]]), 3.0) == [(0, 1)]
    assert assign(np.zeros((0, 3)), 3.0) == []
