import math

import pytest

from cuas.geometry import angle_difference_deg, bearing_to, wrap_azimuth

ORIGIN = (0.0, 0.0, 0.0)
TOLERANCE = 1e-9


@pytest.mark.parametrize(
    ("target", "azimuth", "elevation"),
    [
        ((0.0, 100.0, 0.0), 0.0, 0.0),  # north
        ((100.0, 0.0, 0.0), 90.0, 0.0),  # east
        ((0.0, -100.0, 0.0), 180.0, 0.0),  # south
        ((-100.0, 0.0, 0.0), 270.0, 0.0),  # west
        ((100.0, 100.0, 0.0), 45.0, 0.0),  # north-east
        ((0.0, 100.0, 100.0), 0.0, 45.0),  # up at 45 degrees
        ((0.0, 100.0, -100.0), 0.0, -45.0),  # down at 45 degrees
    ],
)
def test_bearing_from_a_known_position(
    target: tuple[float, float, float], azimuth: float, elevation: float
) -> None:
    az, el, _ = bearing_to(ORIGIN, target)
    assert az == pytest.approx(azimuth, abs=TOLERANCE)
    assert el == pytest.approx(elevation, abs=TOLERANCE)


def test_bearing_from_a_real_station() -> None:
    st1 = (0.0, 288.7, 15.0)
    az, el, range_m = bearing_to(st1, (0.0, 0.0, 15.0 + 288.7))
    assert az == pytest.approx(180.0, abs=TOLERANCE)
    assert el == pytest.approx(45.0, abs=TOLERANCE)
    assert range_m == pytest.approx(288.7 * math.sqrt(2), abs=TOLERANCE)


def test_range_is_three_dimensional() -> None:
    assert bearing_to(ORIGIN, (3.0, 4.0, 12.0))[2] == pytest.approx(13.0, abs=TOLERANCE)


def test_bearing_inverts_the_design_direction_formula() -> None:
    target = (120.0, -340.0, 75.0)
    azimuth_deg, elevation_deg, range_m = bearing_to(ORIGIN, target)
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    # design.md A1: d = (sin(az) cos(el), cos(az) cos(el), sin(el))
    rebuilt = (
        range_m * math.sin(az) * math.cos(el),
        range_m * math.cos(az) * math.cos(el),
        range_m * math.sin(el),
    )
    assert rebuilt == pytest.approx(target, abs=TOLERANCE)


@pytest.mark.parametrize(
    ("raw", "wrapped"),
    [(0.0, 0.0), (360.0, 0.0), (-90.0, 270.0), (725.0, 5.0), (359.5, 359.5)],
)
def test_wrap_azimuth(raw: float, wrapped: float) -> None:
    assert wrap_azimuth(raw) == wrapped


def test_a_tiny_negative_azimuth_wraps_to_zero_not_360() -> None:
    assert -1e-17 % 360.0 == 360.0  # the float trap this guards against
    assert wrap_azimuth(-1e-17) == 0.0


@pytest.mark.parametrize(
    ("a", "b", "difference"),
    [
        (10.0, 350.0, 20.0),
        (350.0, 10.0, -20.0),
        (90.0, 90.0, 0.0),
        (0.0, 180.0, -180.0),
    ],
)
def test_angle_difference_takes_the_short_way_round(
    a: float, b: float, difference: float
) -> None:
    assert angle_difference_deg(a, b) == difference
