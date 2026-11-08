"""Zoom scheduler (docs/design.md A9): the most threatening tracks get the zoom cameras.

Every ``period_s``: highest score first, each confirmed track gets the nearest free camera that
can reach it. A camera stays on its track for ``dwell_s``, unless a track scoring at least
``preempt_margin`` more needs it. Every busy camera gets a task each period, so it follows its
track. Zoom only adds look evidence; it never places a target.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from cuas.config import ZoomSettings
from cuas.geometry import bearing_to
from cuas.schemas import SensorStatus, Track, ZoomTask
from cuas.schemas.base import Vector3

FULL_VISIBILITY = 1.0
# A task takes effect one period after it is issued and holds until the next one, so it aims
# where the track will be halfway through that period.
LEAD_PERIODS = 1.5


@dataclass
class _Duty:
    track_id: str
    since: float
    score: float


class ZoomScheduler:
    def __init__(
        self,
        settings: ZoomSettings,
        per_station: int,
        stations: Mapping[str, Vector3],
        sensor: str,
        base_reach_m: float,
    ) -> None:
        self._settings = settings
        self._stations = {
            sid: np.asarray(p, dtype=float) for sid, p in stations.items()
        }
        self._cameras = [
            (sid, f"z{n}")
            for sid in sorted(stations)
            for n in range(1, per_station + 1)
        ]
        self._sensor = sensor
        self._base_reach_m = base_reach_m
        self._visibility = dict.fromkeys(stations, FULL_VISIBILITY)
        self._duties: dict[tuple[str, str], _Duty] = {}
        self._next_run: float | None = None

    def report(self, status: SensorStatus) -> None:
        station_id, _, sensor = status.sensor_id.partition(".")
        if sensor == self._sensor and station_id in self._visibility:
            self._visibility[station_id] = status.visibility_factor

    def update(
        self, t: float, tracks: Sequence[Track], scores: Mapping[str, float]
    ) -> list[ZoomTask]:
        if not self._cameras or (self._next_run is not None and t < self._next_run):
            return []
        self._next_run = t + self._settings.period_s - 1e-9
        confirmed = {tr.track_id: tr for tr in tracks if tr.status == "confirmed"}
        self._duties = {
            c: d for c, d in self._duties.items() if d.track_id in confirmed
        }
        for duty in self._duties.values():
            duty.score = scores.get(duty.track_id, 0.0)
        busy_tracks = {d.track_id for d in self._duties.values()}
        order = sorted(confirmed, key=lambda tid: (-scores.get(tid, 0.0), tid))
        for track_id in order:
            if track_id not in busy_tracks:
                camera = self._camera_for(
                    t, confirmed[track_id], scores.get(track_id, 0.0)
                )
                if camera is not None:
                    self._duties[camera] = _Duty(track_id, t, scores.get(track_id, 0.0))
                    busy_tracks = {d.track_id for d in self._duties.values()}
        return [
            self._task(t, camera, confirmed[d.track_id])
            for camera, d in sorted(self._duties.items())
        ]

    def _camera_for(
        self, t: float, track: Track, score: float
    ) -> tuple[str, str] | None:
        """The nearest free camera that reaches the track, else the nearest one it may take."""
        reachable = [
            (self._distance(c[0], track), c)
            for c in self._cameras
            if self._reaches(c[0], track)
        ]
        reachable.sort()
        for _, camera in reachable:
            if camera not in self._duties:
                return camera
        for _, camera in reachable:
            duty = self._duties[camera]
            settled = t - duty.since >= self._settings.dwell_s and score > duty.score
            urgent = score >= duty.score + self._settings.preempt_margin
            if settled or urgent:
                return camera
        return None

    def _distance(self, station_id: str, track: Track) -> float:
        return float(
            np.linalg.norm(
                np.asarray(track.position_enu_m) - self._stations[station_id]
            )
        )

    def _reaches(self, station_id: str, track: Track) -> bool:
        reach = (
            self._settings.magnification
            * self._base_reach_m
            * self._visibility[station_id]
        )
        return self._distance(station_id, track) < reach

    def _task(self, t: float, camera: tuple[str, str], track: Track) -> ZoomTask:
        station_id, camera_id = camera
        lead_s = LEAD_PERIODS * self._settings.period_s
        ahead = (
            np.asarray(track.position_enu_m) + np.asarray(track.velocity_mps) * lead_s
        )
        azimuth, elevation, _ = bearing_to(self._stations[station_id], ahead.tolist())
        return ZoomTask(
            station_id=station_id,
            t=t,
            camera_id=camera_id,
            track_id=track.track_id,
            azimuth_deg=azimuth,
            elevation_deg=elevation,
        )
