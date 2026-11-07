"""Threat ranking (docs/design.md A8): zones and time to impact give each track a score and level.

``score = P_hostile * (zone_share * zone_w + (1 - zone_share) * urgency)``, where
``P_hostile = P_drone * (1 - P_friendly)``. Time to impact projects the track's ground velocity
into the critical zone: 0 inside it, ``None`` if the path misses.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from cuas.config import ApprovedFlight, ThreatSettings, Zone, ZoneLabels
from cuas.control.classify import Classified

LEVELS = ("info", "amber", "red")
CRITICAL = "critical"
STILL_MPS = 1e-6  # slower than this, a track is going nowhere
Point = tuple[float, float]


@dataclass(frozen=True)
class Assessment:
    track_id: str
    t: float
    score: float
    level: str
    zone: str | None
    time_to_impact_s: float | None
    reasons: tuple[str, ...]


def inside(point: Point, polygon: Sequence[Point]) -> bool:
    """Even-odd rule: does a ray to the east cross the boundary an odd number of times?"""
    x, y = point
    crossings = 0
    for (x1, y1), (x2, y2) in zip(polygon, [*polygon[1:], polygon[0]], strict=True):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            crossings += 1
    return crossings % 2 == 1


def time_to_impact(
    position: Point, velocity: Point, polygon: Sequence[Point]
) -> float | None:
    if inside(position, polygon):
        return 0.0
    px, py = position
    vx, vy = velocity
    if math.hypot(vx, vy) < STILL_MPS:
        return None
    hits = []
    for (ax, ay), (bx, by) in zip(polygon, [*polygon[1:], polygon[0]], strict=True):
        ex, ey = bx - ax, by - ay
        denominator = vx * ey - vy * ex
        if denominator == 0.0:
            continue  # moving parallel to this edge
        t = ((ax - px) * ey - (ay - py) * ex) / denominator
        s = ((ax - px) * vy - (ay - py) * vx) / denominator
        if t >= 0.0 and 0.0 <= s <= 1.0:
            hits.append(t)
    return min(hits) if hits else None


def urgency(tti: float | None, settings: ThreatSettings) -> float:
    """1.0 within ``urgency_full_s``, a straight ramp down to ``urgency_at_floor`` at
    ``urgency_floor_s``, and ``urgency_beyond`` after that or with no zone ahead."""
    if tti is None or tti > settings.urgency_floor_s:
        return settings.urgency_beyond
    if tti <= settings.urgency_full_s:
        return 1.0
    ramp = (tti - settings.urgency_full_s) / (
        settings.urgency_floor_s - settings.urgency_full_s
    )
    return 1.0 - ramp * (1.0 - settings.urgency_at_floor)


def level_of(score: float, settings: ThreatSettings) -> str:
    if score >= settings.red:
        return "red"
    return "amber" if score >= settings.amber else "info"


def approved(
    position: tuple[float, float, float], t: float, flights: Sequence[ApprovedFlight]
) -> bool:
    x, y, z = position
    return any(
        f.start_s <= t <= f.end_s
        and f.min_altitude_m <= z <= f.max_altitude_m
        and inside((x, y), f.corridor_enu_m)
        for f in flights
    )


class ThreatRanker:
    def __init__(
        self, settings: ThreatSettings, zones: Sequence[Zone], labels: ZoneLabels
    ) -> None:
        self._settings = settings
        self._zones = sorted(zones, key=lambda z: -z.weight)  # the most important first
        self._critical = next(z for z in zones if z.id == CRITICAL)
        self._labels = labels

    def assess(self, t: float, classified: Classified) -> Assessment:
        settings = self._settings
        track = classified.track
        x, y, _ = track.position_enu_m
        tti = time_to_impact(
            (x, y), track.velocity_mps[:2], self._critical.polygon_enu_m
        )
        zone = self._critical if tti is not None else self._zone_at((x, y))
        friendly = approved(track.position_enu_m, t, settings.approved_flights)
        p_hostile = 0.0 if friendly else classified.track_class.p_drone
        weight = zone.weight if zone is not None else 0.0
        mix = settings.zone_share * weight + (1.0 - settings.zone_share) * urgency(
            tti, settings
        )
        score = p_hostile * mix
        return Assessment(
            track.track_id,
            t,
            score,
            level_of(score, settings),
            zone.id if zone is not None else None,
            tti,
            self._reasons(classified, zone, tti, friendly),
        )

    def _zone_at(self, point: Point) -> Zone | None:
        return next((z for z in self._zones if inside(point, z.polygon_enu_m)), None)

    def _reasons(
        self,
        classified: Classified,
        zone: Zone | None,
        tti: float | None,
        friendly: bool,
    ) -> tuple[str, ...]:
        reasons = [] if classified.move_reason is None else [classified.move_reason]
        evidence = classified.track_class.evidence
        if evidence.look is not None:
            reasons.append(f"camera look {evidence.look:.0%} drone")
        if classified.engine_heard:
            reasons.append("engine heard")
        if zone is not None:
            label = getattr(self._labels, zone.id)
            if tti == 0.0:
                reasons.append(f"inside {label}")
            elif tti is not None:
                reasons.append(f"heading to {label}, {tti:.0f} s")
            else:
                reasons.append(f"in {label}")
        if friendly:
            reasons.append("approved flight")
        return tuple(reasons)


def rank(assessments: Sequence[Assessment]) -> list[Assessment]:
    """Level first, then time to impact (none last), then score: the order the operator acts in."""
    return sorted(
        assessments,
        key=lambda a: (
            -LEVELS.index(a.level),
            math.inf if a.time_to_impact_s is None else a.time_to_impact_s,
            -a.score,
            a.track_id,
        ),
    )
