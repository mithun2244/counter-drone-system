"""Triangulation: the 3D point nearest to several bearing rays (docs/design.md A5).

A point comes back only when the rays can support it. Otherwise the reason they cannot.
"""

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from cuas.config import TrackerSettings
from cuas.geometry import bearing_direction
from cuas.schemas import BearingDetection
from cuas.schemas.base import Vector3

IDENTITY = np.eye(3)
NEVER_MEET = 1e-12  # below this, |d1 x d2| means the two lines never cross at one point
MIN_RANGE_M = 1.0  # keeps the covariance finite for a point right on top of a station


@dataclass(frozen=True)
class Ray:
    """One bearing as a ray from its station's surveyed position."""

    station_id: str
    sensor: str
    origin: np.ndarray
    direction: np.ndarray
    sigma_deg: float

    @classmethod
    def from_bearing(cls, bearing: BearingDetection, origin: Vector3) -> "Ray":
        direction = bearing_direction(bearing.azimuth_deg, bearing.elevation_deg)
        return cls(
            bearing.station_id,
            bearing.sensor,
            np.asarray(origin, dtype=float),
            np.asarray(direction),
            bearing.sigma_deg,
        )


@dataclass(frozen=True)
class Fix:
    position: np.ndarray
    covariance: np.ndarray
    stations: frozenset[str]


@dataclass(frozen=True)
class NoFix:
    """``one_station``, ``parallel``, ``miss`` or ``behind``."""

    reason: str


def triangulate(rays: Sequence[Ray], settings: TrackerSettings) -> Fix | NoFix:
    stations = frozenset(ray.station_id for ray in rays)
    if len(stations) < 2:
        return NoFix("one_station")
    pairs = [
        (a, b)
        for a, b in itertools.combinations(rays, 2)
        if a.station_id != b.station_id
    ]
    if max(line_angle_deg(a, b) for a, b in pairs) < settings.min_ray_angle_deg:
        return NoFix("parallel")
    if not all(rays_meet(a, b, settings) for a, b in pairs):
        return NoFix("miss")
    position = nearest_point(rays)
    if any(float((position - ray.origin) @ ray.direction) <= 0.0 for ray in rays):
        return NoFix("behind")
    return Fix(position, covariance_at(position, rays), stations)


def line_angle_deg(a: Ray, b: Ray) -> float:
    """Angle between the two lines, 0 to 90 degrees, so rays facing each other count as parallel."""
    cross = float(np.linalg.norm(np.cross(a.direction, b.direction)))
    return math.degrees(math.atan2(cross, abs(float(a.direction @ b.direction))))


def rays_meet(a: Ray, b: Ray, settings: TrackerSettings) -> bool:
    """Closest distance under the fixed limit, and under what the bearing noise allows at range."""
    cross = np.cross(a.direction, b.direction)
    norm = float(np.linalg.norm(cross))
    if norm < NEVER_MEET:
        return False
    miss = abs(float((b.origin - a.origin) @ cross)) / norm
    if miss >= settings.max_ray_miss_m:
        return False
    point = nearest_point((a, b))
    allowed = settings.ray_miss_sigmas * math.hypot(
        cross_range_sigma_m(a, point), cross_range_sigma_m(b, point)
    )
    return miss <= allowed


def nearest_point(rays: Sequence[Ray]) -> np.ndarray:
    """``A p = b`` with ``A = sum w (I - d d^T)``, ``b = sum w (I - d d^T) s``, ``w = 1/sigma^2``."""
    a_sum, b_sum = np.zeros((3, 3)), np.zeros(3)
    for ray in rays:
        weighted = (
            IDENTITY - np.outer(ray.direction, ray.direction)
        ) / ray.sigma_deg**2
        a_sum += weighted
        b_sum += weighted @ ray.origin
    return np.linalg.solve(a_sum, b_sum)


def cross_range_sigma_m(ray: Ray, point: np.ndarray) -> float:
    """One sigma of bearing noise, in metres, at the point's distance from the station."""
    range_m = max(float(np.linalg.norm(point - ray.origin)), MIN_RANGE_M)
    return math.radians(ray.sigma_deg) * range_m


def covariance_at(point: np.ndarray, rays: Sequence[Ray]) -> np.ndarray:
    """Position covariance. Weighting by range stretches it along the line of sight."""
    information = np.zeros((3, 3))
    for ray in rays:
        across = IDENTITY - np.outer(ray.direction, ray.direction)
        information += across / cross_range_sigma_m(ray, point) ** 2
    return np.linalg.inv(information)


def explains(ray: Ray, point: np.ndarray, settings: TrackerSettings) -> float | None:
    """How far the ray passes from the point, if it points at it within its noise; else ``None``."""
    offset = point - ray.origin
    along = float(offset @ ray.direction)
    if along <= 0.0:
        return None
    distance = float(np.linalg.norm(offset - along * ray.direction))
    allowed = (
        settings.ray_miss_sigmas * math.radians(ray.sigma_deg) * along
        + settings.ray_join_m
    )
    return distance if distance <= allowed else None
