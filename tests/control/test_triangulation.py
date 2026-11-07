"""Known-answer tests for triangulation (docs/design.md A5)."""

import math

import numpy as np
import pytest

from cuas.config import SiteConfig, TrackerSettings
from cuas.control.triangulation import (
    Fix,
    NoFix,
    Ray,
    explains,
    line_angle_deg,
    triangulate,
)

EXACT = 1e-6
BASELINE_M = 500.0
STATION_A = np.array([0.0, 0.0, 0.0])
STATION_B = np.array([BASELINE_M, 0.0, 0.0])
RGB_SIGMA = 0.05


def ray_to(station_id: str, origin, target, sigma: float = RGB_SIGMA) -> Ray:
    offset = np.asarray(target, dtype=float) - origin
    return Ray(station_id, "rgb", origin, offset / np.linalg.norm(offset), sigma)


@pytest.fixture
def settings(site: SiteConfig) -> TrackerSettings:
    return site.tracker


def fix_of(rays: list[Ray], settings: TrackerSettings) -> Fix:
    result = triangulate(rays, settings)
    assert isinstance(result, Fix), result
    return result


def test_two_perfect_rays_give_the_exact_point(settings: TrackerSettings) -> None:
    target = (250.0, 800.0, 90.0)
    rays = [ray_to("a", STATION_A, target), ray_to("b", STATION_B, target)]
    result = fix_of(rays, settings)
    assert result.position == pytest.approx(target, abs=EXACT)
    assert result.stations == {"a", "b"}


def test_three_perfect_rays_give_the_exact_point(settings: TrackerSettings) -> None:
    target = (-120.0, 640.0, 75.0)
    origins = [STATION_A, STATION_B, np.array([250.0, -433.0, 15.0])]
    rays = [ray_to(name, o, target) for name, o in zip("abc", origins, strict=True)]
    assert fix_of(rays, settings).position == pytest.approx(target, abs=EXACT)


def target_at_angle(angle_deg: float) -> tuple[float, float, float]:
    """A point on the baseline's perpendicular where the two rays meet at this angle."""
    return (BASELINE_M / 2, BASELINE_M / 2 / math.tan(math.radians(angle_deg / 2)), 0.0)


@pytest.mark.parametrize(("angle", "accepted"), [(14.9, False), (15.1, True)])
def test_near_parallel_rays_are_rejected(
    settings: TrackerSettings, angle: float, accepted: bool
) -> None:
    target = target_at_angle(angle)
    rays = [ray_to("a", STATION_A, target), ray_to("b", STATION_B, target)]
    assert line_angle_deg(*rays) == pytest.approx(angle)
    result = triangulate(rays, settings)
    if accepted:
        assert result.position == pytest.approx(target, abs=1e-3)
    else:
        assert result == NoFix("parallel")


def test_exactly_parallel_rays_are_rejected_without_error(
    settings: TrackerSettings,
) -> None:
    north = np.array([0.0, 1.0, 0.0])
    rays = [
        Ray("a", "rgb", STATION_A, north, RGB_SIGMA),
        Ray("b", "rgb", STATION_B, north, RGB_SIGMA),
    ]
    assert triangulate(rays, settings) == NoFix("parallel")


def test_rays_facing_each_other_count_as_parallel(settings: TrackerSettings) -> None:
    middle = (BASELINE_M / 2, 0.0, 0.0)
    rays = [ray_to("a", STATION_A, middle), ray_to("b", STATION_B, middle)]
    assert line_angle_deg(*rays) == pytest.approx(0.0, abs=EXACT)
    assert triangulate(rays, settings) == NoFix("parallel")


def test_two_sensors_at_one_station_give_a_direction_not_a_point(
    settings: TrackerSettings,
) -> None:
    target = (250.0, 800.0, 90.0)
    rays = [ray_to("a", STATION_A, target), ray_to("a", STATION_A, target, sigma=0.1)]
    assert triangulate(rays, settings) == NoFix("one_station")


def test_lines_that_cross_behind_the_stations_are_rejected(
    settings: TrackerSettings,
) -> None:
    behind = np.array([250.0, -250.0, 0.0])
    rays = [
        Ray(
            "a",
            "rgb",
            STATION_A,
            (STATION_A - behind) / np.linalg.norm(STATION_A - behind),
            RGB_SIGMA,
        ),
        Ray(
            "b",
            "rgb",
            STATION_B,
            (STATION_B - behind) / np.linalg.norm(STATION_B - behind),
            RGB_SIGMA,
        ),
    ]
    assert triangulate(rays, settings) == NoFix("behind")


def skew_rays(lift_m: float, sigma: float) -> list[Ray]:
    """Ray b aims ``lift_m`` above ray a's target, so the two lines pass each other."""
    return [
        ray_to("a", STATION_A, (250.0, 1000.0, 0.0), sigma),
        ray_to("b", STATION_B, (250.0, 1000.0, lift_m), sigma),
    ]


def test_rays_that_miss_by_30_m_or_more_are_rejected_whatever_the_noise(
    settings: TrackerSettings,
) -> None:
    assert triangulate(skew_rays(80.0, sigma=5.0), settings) == NoFix("miss")


def test_a_miss_is_judged_against_the_bearing_noise(settings: TrackerSettings) -> None:
    """The same 12 m lift is too far for a 0.05 degree camera, but fine for a 1 degree one."""
    assert triangulate(skew_rays(12.0, sigma=RGB_SIGMA), settings) == NoFix("miss")
    assert isinstance(triangulate(skew_rays(12.0, sigma=1.0), settings), Fix)


def test_the_point_leans_towards_the_more_precise_ray(
    settings: TrackerSettings,
) -> None:
    rgb, thermal = skew_rays(2.0, sigma=RGB_SIGMA)[0], skew_rays(2.0, sigma=0.1)[1]
    point = fix_of([rgb, thermal], settings).position

    def distance(ray: Ray) -> float:
        offset = point - ray.origin
        return float(np.linalg.norm(offset - (offset @ ray.direction) * ray.direction))

    assert distance(rgb) < distance(thermal)


def test_uncertainty_stretches_along_the_line_of_sight(
    settings: TrackerSettings,
) -> None:
    target = np.array([250.0, 1500.0, 80.0])
    rays = [ray_to("a", STATION_A, target), ray_to("b", STATION_B, target)]
    values, vectors = np.linalg.eigh(fix_of(rays, settings).covariance)
    line_of_sight = target - (STATION_A + STATION_B) / 2
    line_of_sight /= np.linalg.norm(line_of_sight)
    assert values[-1] > 10 * values[-2]
    assert abs(float(vectors[:, -1] @ line_of_sight)) > 0.99


def test_explains_accepts_a_ray_through_the_point_and_refuses_one_behind(
    settings: TrackerSettings,
) -> None:
    point = np.array([250.0, 800.0, 90.0])
    through = ray_to("a", STATION_A, point)
    assert explains(through, point, settings) == pytest.approx(0.0, abs=EXACT)
    away = Ray("a", "rgb", STATION_A, -through.direction, RGB_SIGMA)
    assert explains(away, point, settings) is None
    wide = ray_to("b", STATION_B, point + np.array([0.0, 0.0, 50.0]))
    assert explains(wide, point, settings) is None
