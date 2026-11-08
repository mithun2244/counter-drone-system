"""Simulated zoom cameras (docs/design.md A9). Recorded media only, and never a position.

A camera points where its latest task aimed, once that task is a scheduler period old. A target
inside its narrow view gets a real RGB look, chosen as if the target were ``magnification``
times closer. Zoom bearings carry class evidence; the tracker never triangulates them.
"""

from collections.abc import Sequence

from cuas.config import SiteConfig, TargetType
from cuas.geometry import (
    angle_difference_deg,
    bearing_to,
    clamp_elevation,
    wrap_azimuth,
)
from cuas.schemas import BearingDetection, ZoomTask
from cuas.sim.rng import stream
from cuas.sim.scenario import Environment
from cuas.sim.station import LookSource, Observation, detection_probability
from cuas.sim.truth import BearingTruth

ZOOM = "zoom"
LOOKS_LIKE = "rgb"  # a zoom camera is a magnified RGB camera
EARLY = 1e-9


class ZoomSim:
    def __init__(
        self,
        site: SiteConfig,
        environment: Environment,
        seed: int,
        media: LookSource,
    ) -> None:
        self._settings = site.zoom
        self._camera = site.sensors[LOOKS_LIKE]
        self._visibility = environment.visibility_factor
        self._stations = {s.id: s.position_enu_m for s in site.stations}
        self._seed = seed
        self._media = media
        self._waiting: list[ZoomTask] = []
        self._pointing: dict[tuple[str, str], ZoomTask] = {}

    def task(self, task: ZoomTask) -> None:
        self._waiting.append(task)

    def point(self, t: float) -> None:
        """Apply every task issued at least one scheduler period before ``t``."""
        due = t - self._settings.period_s + EARLY
        for task in [task for task in self._waiting if task.t <= due]:
            self._pointing[(task.station_id, task.camera_id)] = task
        self._waiting = [task for task in self._waiting if task.t > due]

    def observe(
        self,
        target_id: str,
        target_type: TargetType,
        position: Sequence[float],
        t: float,
    ) -> list[Observation]:
        return [
            observation
            for (station_id, camera_id), task in sorted(self._pointing.items())
            if (
                observation := self._look(
                    station_id, camera_id, task, target_id, target_type, position, t
                )
            )
        ]

    def _look(
        self,
        station_id: str,
        camera_id: str,
        task: ZoomTask,
        target_id: str,
        target_type: TargetType,
        position: Sequence[float],
        t: float,
    ) -> Observation | None:
        settings, camera = self._settings, self._camera
        azimuth, elevation, range_m = bearing_to(self._stations[station_id], position)
        off_azimuth = abs(angle_difference_deg(azimuth, task.azimuth_deg))
        off_elevation = abs(elevation - task.elevation_deg)
        if max(off_azimuth, off_elevation) > settings.half_fov_deg:
            return None
        rng = stream(self._seed, "zoom", station_id, camera_id, target_id)
        chance = rng.random()
        azimuth_noise, elevation_noise = rng.standard_normal(2).tolist()
        max_range_m = (
            camera.base_range_m[target_type] * settings.magnification * self._visibility
        )
        if chance >= detection_probability(range_m, max_range_m, camera.p0):
            return None
        look = self._media.look(
            station_id,
            ZOOM,
            target_id,
            target_type,
            range_m / settings.magnification,
            t,
        )
        if look is None:
            return (
                None  # nothing stands in for this target, so the camera reports nothing
            )
        sigma_deg = camera.sigma_deg / settings.magnification
        bearing = BearingDetection(
            station_id=station_id,
            sensor=ZOOM,
            t=t,
            azimuth_deg=wrap_azimuth(azimuth + sigma_deg * azimuth_noise),
            elevation_deg=clamp_elevation(elevation + sigma_deg * elevation_noise),
            sigma_deg=sigma_deg,
            class_probs=look.class_probs,
            snapshot_ref=look.snapshot_ref,
        )
        truth = BearingTruth(
            t=t,
            target_id=target_id,
            target_type=target_type,
            station_id=station_id,
            sensor=ZOOM,
            azimuth_deg=azimuth,
            elevation_deg=elevation,
            range_m=range_m,
            max_range_m=max_range_m,
        )
        return bearing, truth
