"""Acoustic sector tracks (docs/design.md A6): a heard direction that cannot be placed in 3D.

A picket alert, or a station acoustic bearing that no 3D track explains, becomes a wedge from the
sensor's surveyed position. Nothing here ever produces a position or a range.
"""

from dataclasses import dataclass

from cuas.geometry import angle_difference_deg
from cuas.schemas import SectorTrack
from cuas.schemas.base import Vector3

REFRESH_HALF_WIDTHS = 2.0  # a report this many half-widths from a sector refreshes it


@dataclass
class _Sector:
    sector_id: str
    sensor_id: str
    origin: Vector3
    bearing_deg: float
    half_width_deg: float
    last_t: float
    reports: int


class SectorTracker:
    def __init__(self, lost_after_s: float) -> None:
        self._lost_after_s = lost_after_s
        self._sectors: list[_Sector] = []
        self._started = 0

    def report(
        self,
        sensor_id: str,
        origin: Vector3,
        t: float,
        bearing_deg: float,
        half_width_deg: float,
    ) -> SectorTrack:
        """Refresh this sensor's nearest live sector if the report falls near it, else start one."""
        nearby = [
            (abs(angle_difference_deg(bearing_deg, s.bearing_deg)), index)
            for index, s in enumerate(self._sectors)
            if s.sensor_id == sensor_id
            and abs(angle_difference_deg(bearing_deg, s.bearing_deg))
            <= REFRESH_HALF_WIDTHS * half_width_deg
        ]
        if nearby:
            sector = self._sectors[min(nearby)[1]]
            sector.bearing_deg, sector.last_t = bearing_deg, t
            sector.half_width_deg = half_width_deg
            sector.reports += 1
        else:
            self._started += 1
            sector = _Sector(
                f"sec-{self._started}",
                sensor_id,
                origin,
                bearing_deg,
                half_width_deg,
                t,
                1,
            )
            self._sectors.append(sector)
        return _message(sector, t, "active")

    def expire(self, t: float) -> list[SectorTrack]:
        """Sectors with no report for ``lost_after_s``, each announced once as lost."""
        lost = [s for s in self._sectors if t - s.last_t > self._lost_after_s]
        self._sectors = [s for s in self._sectors if s not in lost]
        return [_message(s, t, "lost") for s in lost]


def _message(sector: _Sector, t: float, status: str) -> SectorTrack:
    return SectorTrack(
        sector_id=sector.sector_id,
        t=t,
        sensor_id=sector.sensor_id,
        origin_enu_m=sector.origin,
        bearing_deg=sector.bearing_deg,
        half_width_deg=min(sector.half_width_deg, 180.0),
        reports=sector.reports,
        status=status,
    )
