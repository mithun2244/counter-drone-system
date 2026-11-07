"""Bearing geometry in the local ENU frame (docs/design.md A1).

Lives outside ``sim/`` so the tracker can use the same maths without touching ground truth.
"""

import math
from collections.abc import Sequence

FULL_CIRCLE_DEG = 360.0
HALF_CIRCLE_DEG = 180.0
RIGHT_ANGLE_DEG = 90.0


def wrap_azimuth(azimuth_deg: float) -> float:
    """Wrap to [0, 360). A tiny negative input rounds to exactly 360 under ``%``, so fold that."""
    wrapped = azimuth_deg % FULL_CIRCLE_DEG
    return 0.0 if wrapped == FULL_CIRCLE_DEG else wrapped


def clamp_elevation(elevation_deg: float) -> float:
    return max(-RIGHT_ANGLE_DEG, min(RIGHT_ANGLE_DEG, elevation_deg))


def angle_difference_deg(a_deg: float, b_deg: float) -> float:
    """Smallest signed turn from b to a, in [-180, 180)."""
    return (a_deg - b_deg + HALF_CIRCLE_DEG) % FULL_CIRCLE_DEG - HALF_CIRCLE_DEG


def bearing_direction(
    azimuth_deg: float, elevation_deg: float
) -> tuple[float, float, float]:
    """Unit vector along a bearing: (sin az cos el, cos az cos el, sin el), design.md A1."""
    azimuth, elevation = math.radians(azimuth_deg), math.radians(elevation_deg)
    return (
        math.sin(azimuth) * math.cos(elevation),
        math.cos(azimuth) * math.cos(elevation),
        math.sin(elevation),
    )


def bearing_to(
    origin: Sequence[float], target: Sequence[float]
) -> tuple[float, float, float]:
    """Azimuth (0 = north, clockwise) and elevation in degrees, and range in metres."""
    east, north, up = (float(t) - float(o) for t, o in zip(target, origin, strict=True))
    ground = math.hypot(east, north)
    azimuth = wrap_azimuth(math.degrees(math.atan2(east, north)))
    elevation = math.degrees(math.atan2(up, ground))
    return azimuth, elevation, math.hypot(ground, up)
