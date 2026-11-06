"""Simulated station sensors: field of view, range, detection chance, noise (docs/design.md A2)."""

from collections.abc import Sequence

import numpy as np

from cuas.config import Placement, SensorSettings, SiteConfig, TargetType
from cuas.geometry import (
    angle_difference_deg,
    bearing_to,
    clamp_elevation,
    wrap_azimuth,
)
from cuas.schemas import BearingDetection, SensorKind, SensorStatus
from cuas.sim.rng import stream
from cuas.sim.scenario import Environment
from cuas.sim.truth import BearingTruth

Observation = tuple[BearingDetection, BearingTruth]


def detection_probability(range_m: float, max_range_m: float, p0: float) -> float:
    """``p0 * (1 - (r / R)^2)`` inside the range, and 0 at the range and beyond."""
    if range_m >= max_range_m:
        return 0.0
    return p0 * (1.0 - (range_m / max_range_m) ** 2)


def in_field_of_view(
    azimuth_deg: float, elevation_deg: float, settings: SensorSettings
) -> bool:
    off_axis = abs(angle_difference_deg(azimuth_deg, settings.boresight_az_deg))
    return (
        off_axis <= settings.hfov_deg / 2.0
        and settings.min_elevation_deg <= elevation_deg <= settings.max_elevation_deg
    )


class StationSim:
    """One station's sensors. Cameras lose range to visibility, acoustic sensors to wind."""

    def __init__(
        self, station: Placement, site: SiteConfig, environment: Environment, seed: int
    ) -> None:
        self._station = station
        self._sensors = site.sensors
        self._seed = seed
        wind_factor = environment.wind_range_factor(site.simulation)
        self._range_factors: dict[SensorKind, float] = {
            "rgb": environment.visibility_factor,
            "thermal": environment.visibility_factor,
            "acoustic": wind_factor,
        }
        self._streams: dict[tuple[SensorKind, str], np.random.Generator] = {}

    def _stream(self, sensor: SensorKind, target_id: str) -> np.random.Generator:
        key = (sensor, target_id)
        if key not in self._streams:
            self._streams[key] = stream(
                self._seed, "bearing", self._station.id, sensor, target_id
            )
        return self._streams[key]

    def observe(
        self,
        target_id: str,
        target_type: TargetType,
        position: Sequence[float],
        t: float,
    ) -> list[Observation]:
        """What each sensor reports about one target on this tick."""
        geometry = bearing_to(self._station.position_enu_m, position)
        observations = (
            self._sense(sensor, target_id, target_type, geometry, t)
            for sensor in self._sensors
        )
        return [observation for observation in observations if observation]

    def _sense(
        self,
        sensor: SensorKind,
        target_id: str,
        target_type: TargetType,
        geometry: tuple[float, float, float],
        t: float,
    ) -> Observation | None:
        azimuth, elevation, range_m = geometry
        settings = self._sensors[sensor]
        # Drawn every tick, detected or not, so noise lines up across runs that differ only
        # in range, such as S2 and S4.
        rng = self._stream(sensor, target_id)
        chance = rng.random()
        azimuth_noise, elevation_noise = rng.standard_normal(2).tolist()
        max_range_m = settings.base_range_m[target_type] * self._range_factors[sensor]
        if not in_field_of_view(azimuth, elevation, settings):
            return None
        if chance >= detection_probability(range_m, max_range_m, settings.p0):
            return None
        # MOCK: geometry and noise are simulated; class_probs and snapshot_ref stay empty
        # until the real models arrive in Phase 2.
        bearing = BearingDetection(
            station_id=self._station.id,
            sensor=sensor,
            t=t,
            azimuth_deg=wrap_azimuth(azimuth + settings.sigma_deg * azimuth_noise),
            elevation_deg=clamp_elevation(
                elevation + settings.sigma_deg * elevation_noise
            ),
            sigma_deg=settings.sigma_deg,
        )
        truth = BearingTruth(
            t=t,
            target_id=target_id,
            target_type=target_type,
            station_id=self._station.id,
            sensor=sensor,
            azimuth_deg=azimuth,
            elevation_deg=elevation,
            range_m=range_m,
            max_range_m=max_range_m,
        )
        return bearing, truth

    def statuses(self, t: float) -> list[SensorStatus]:
        # MOCK: simulated sensors never fail.
        return [
            SensorStatus(
                sensor_id=f"{self._station.id}.{sensor}",
                ok=True,
                visibility_factor=factor,
                t=t,
            )
            for sensor, factor in self._range_factors.items()
        ]
