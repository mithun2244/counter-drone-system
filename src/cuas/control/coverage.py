"""Coverage % (docs/design.md A10): the share of one zone that enough stations can still see.

A station's reach is the design target's base range for one sensor, times the visibility that
sensor last reported about itself. Nothing here reads the scenario.
"""

import math
from collections.abc import Mapping, Sequence

import numpy as np

from cuas.config import CoverageSettings, Zone
from cuas.control.threat import inside
from cuas.schemas import CoverageStatus, SensorStatus
from cuas.schemas.base import Vector3

PERCENT = 100.0
FULL_VISIBILITY = 1.0  # until a sensor reports otherwise


def grid(polygon: Sequence[tuple[float, float]], cell_m: float) -> np.ndarray:
    """Centres of the square cells whose centre lies inside the polygon."""
    xs, ys = zip(*polygon, strict=True)
    centres = [
        (x, y)
        for x in np.arange(min(xs) + cell_m / 2, max(xs), cell_m)
        for y in np.arange(min(ys) + cell_m / 2, max(ys), cell_m)
        if inside((float(x), float(y)), polygon)
    ]
    return np.array(centres)


class CoverageMonitor:
    def __init__(
        self,
        settings: CoverageSettings,
        zones: Sequence[Zone],
        stations: Mapping[str, Vector3],
        base_range_m: float,
    ) -> None:
        self._settings = settings
        zone = next(z for z in zones if z.id == settings.zone)
        self._cells = grid(zone.polygon_enu_m, settings.cell_m)
        self._stations = {
            sid: np.asarray(p[:2], dtype=float) for sid, p in stations.items()
        }
        self._base_range_m = base_range_m
        self._visibility = dict.fromkeys(stations, FULL_VISIBILITY)
        self._last: float | None = None

    def report(self, status: SensorStatus) -> None:
        station_id, _, sensor = status.sensor_id.partition(".")
        if sensor == self._settings.sensor and station_id in self._visibility:
            self._visibility[station_id] = status.visibility_factor

    def percent(self) -> float:
        seen_by = np.zeros(len(self._cells), dtype=int)
        for station_id, position in self._stations.items():
            reach = self._base_range_m * self._visibility[station_id]
            # Strictly inside, as the simulator detects: zero visibility sees nothing at all.
            seen_by += np.linalg.norm(self._cells - position, axis=1) < reach
        return PERCENT * float(np.mean(seen_by >= self._settings.min_stations))

    def update(self, t: float) -> CoverageStatus | None:
        """A status when coverage changes, and the first time it is asked."""
        pct = self.percent()
        if self._last is not None and math.isclose(pct, self._last):
            return None
        self._last = pct
        return CoverageStatus(
            t=t, coverage_pct=pct, warning=pct < self._settings.warning_below_pct
        )
