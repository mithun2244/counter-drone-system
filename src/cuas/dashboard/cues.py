"""Big-drone camera cues for the operator's video panel (docs/dashboard_contract.md).

One engagement per picket that hears a piston engine, in three stages:

1. ``acoustic``: from the picket's first sector, the nearest station's camera is cued at the
   picket and searching.
2. ``camera``: the first camera bearing (RGB or thermal, any station) within the search
   half-width of that station's bearing to the picket. Picket bearings err by about 20 degrees,
   so the search is by direction to the picket, not by the wedge. A ``CameraDetection`` note is
   queued for the evidence chain. A confirmed track within reach of the picket then links to it.
3. ``zoom``: a zoom camera is tasked on the linked track.

A wave can bring more drones than pickets heard. A further confirmed track within reach of an
engaged picket gets its own engagement; its camera detection is then the camera bearing that
started its track (each station's newest bearing nearest to it), not an earlier guess.

Built only from bus messages (picket alerts, sectors, bearings, tracks, zoom tasks), never
ground truth. Small drones never start an engagement: they have electric engines, and in every
scenario no picket hears them.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cuas.config import SiteConfig
from cuas.dashboard.contract import CameraCue, SimCameraView
from cuas.geometry import angle_difference_deg, bearing_to
from cuas.schemas import (
    BearingDetection,
    CameraDetection,
    Message,
    PicketAlert,
    SectorTrack,
    ThreatAssessment,
    Track,
    ZoomTask,
)

CAMERAS = ("rgb", "thermal")
PISTON, ELECTRIC = "piston", "electric"


@dataclass
class _Engagement:
    key: str
    picket_id: str
    heard_t: float
    station_id: str
    cue_azimuth_deg: float
    detected: BearingDetection | None = None
    latest: BearingDetection | None = None
    """The newest camera bearing from the detecting station that follows the detected one."""
    track_id: str | None = None


class CueTracker:
    def __init__(self, site: SiteConfig) -> None:
        settings = site.dashboard.camera_cue
        self._half_width_deg = settings.search_half_width_deg
        self._same_target_deg = settings.same_target_deg
        self._span_m = settings.target_span_m
        piston = [
            e.hearing_radius_m
            for e in site.picket_settings.engines.values()
            if e.type == PISTON
        ]
        self._reach_m = settings.link_reach_factor * max(piston, default=0.0)
        self._zoom_fov_deg = 2.0 * site.zoom.half_fov_deg
        self._stations = {s.id: s.position_enu_m for s in site.stations}
        self._pickets = {p.id: p.position_enu_m for p in site.pickets}
        self._votes: dict[str, int] = {}
        """Piston guesses minus electric guesses, per picket."""
        self._engagements: dict[str, _Engagement] = {}
        self._newest: dict[str, BearingDetection] = {}
        """Each station's newest camera bearing."""
        self._notes: list[CameraDetection] = []

    def ingest(self, message: Message) -> None:
        if isinstance(message, PicketAlert):
            probs = message.engine_type_probs
            vote = 1 if probs.get(PISTON, 0.0) > probs.get(ELECTRIC, 0.0) else -1
            self._votes[message.picket_id] = (
                self._votes.get(message.picket_id, 0) + vote
            )
        elif isinstance(message, SectorTrack):
            self._sector(message)
        elif isinstance(message, BearingDetection) and message.sensor in CAMERAS:
            self._ray(message)
        elif isinstance(message, Track):
            self._track(message)

    def take_notes(self) -> list[CameraDetection]:
        """Camera detections since the last call, for the evidence chain."""
        notes, self._notes = self._notes, []
        return notes

    def views(
        self,
        tracks: Mapping[str, Track],
        zoom: Sequence[ZoomTask],
        threats: Mapping[str, ThreatAssessment],
    ) -> list[CameraCue]:
        return [self._cue(e, tracks, zoom, threats) for e in self._engagements.values()]

    def _azimuth_to_picket(self, station_id: str, picket_id: str) -> float:
        azimuth, _, _ = bearing_to(self._stations[station_id], self._pickets[picket_id])
        return azimuth

    def _sector(self, sector: SectorTrack) -> None:
        picket = sector.sensor_id
        if (
            sector.status != "active"
            or picket not in self._pickets
            or picket in self._engagements  # keyed by picket: the first one heard
            or self._votes.get(picket, 0) <= 0
        ):
            return
        position = self._pickets[picket]
        station = min(
            self._stations, key=lambda s: _ground(self._stations[s], position)
        )
        self._engagements[picket] = _Engagement(
            picket, picket, sector.t, station, self._azimuth_to_picket(station, picket)
        )

    def _off_cue(self, ray: BearingDetection, engagement: _Engagement) -> float:
        cue = self._azimuth_to_picket(ray.station_id, engagement.picket_id)
        return abs(angle_difference_deg(ray.azimuth_deg, cue))

    def _same_target(self, ray: BearingDetection, e: _Engagement) -> bool:
        latest = e.latest
        return (
            latest is not None
            and latest.station_id == ray.station_id
            and abs(angle_difference_deg(ray.azimuth_deg, latest.azimuth_deg))
            <= self._same_target_deg
        )

    def _ray(self, ray: BearingDetection) -> None:
        self._newest[ray.station_id] = ray
        followed = [e for e in self._engagements.values() if self._same_target(ray, e)]
        for e in followed:  # the same target, moved on: follow it
            e.latest = ray
        if not followed:  # a target already followed detects nothing new
            self._detect(ray, self._searching(ray))

    def _searching(self, ray: BearingDetection) -> list[_Engagement]:
        return [
            e
            for e in self._engagements.values()
            if e.detected is None
            and ray.t >= e.heard_t
            and self._off_cue(ray, e) <= self._half_width_deg
        ]

    def _detect(self, ray: BearingDetection, searching: list[_Engagement]) -> None:
        if searching:  # one ray is one detection: the engagement it points closest to
            found = min(searching, key=lambda e: self._off_cue(ray, e))
            self._found(found, ray)

    def _found(self, found: _Engagement, ray: BearingDetection) -> None:
        found.detected = found.latest = ray
        self._notes.append(
            CameraDetection(
                t=ray.t,
                picket_id=found.picket_id,
                station_id=ray.station_id,
                sensor=ray.sensor,
                azimuth_deg=ray.azimuth_deg,
                elevation_deg=ray.elevation_deg,
            )
        )

    def _track(self, track: Track) -> None:
        if track.status == "lost":
            for e in self._engagements.values():
                if e.track_id == track.track_id:
                    e.track_id = None
            return
        linked = {e.track_id for e in self._engagements.values()}
        if track.status != "confirmed" or track.track_id in linked:
            return
        free = [
            e
            for e in self._engagements.values()
            if e.detected is not None
            and e.track_id is None
            and _ground(self._pickets[e.picket_id], track.position_enu_m)
            <= self._reach_m
        ]
        if free:
            min(free, key=lambda e: self._distance(e, track)).track_id = track.track_id
            return
        engaged = [
            e
            for e in self._engagements.values()
            if e.detected is not None and self._distance(e, track) <= self._reach_m
        ]
        if engaged:  # one more drone of the wave near an engaged picket
            self._another(min(engaged, key=lambda e: self._distance(e, track)), track)

    def _distance(self, e: _Engagement, track: Track) -> float:
        return _ground(self._pickets[e.picket_id], track.position_enu_m)

    def _another(self, base: _Engagement, track: Track) -> None:
        """Its own engagement, detected by the station bearing that points nearest to it."""
        best, off = None, self._same_target_deg
        for station, ray in self._newest.items():
            azimuth, _, _ = bearing_to(self._stations[station], track.position_enu_m)
            if abs(angle_difference_deg(ray.azimuth_deg, azimuth)) <= off:
                best, off = ray, abs(angle_difference_deg(ray.azimuth_deg, azimuth))
        if best is None:
            return
        key = f"{base.picket_id}-{track.track_id}"
        extra = _Engagement(
            key, base.picket_id, base.heard_t, base.station_id, base.cue_azimuth_deg
        )
        extra.track_id = track.track_id
        self._engagements[key] = extra
        self._found(extra, best)

    def _cue(
        self,
        e: _Engagement,
        tracks: Mapping[str, Track],
        zoom: Sequence[ZoomTask],
        threats: Mapping[str, ThreatAssessment],
    ) -> CameraCue:
        track = tracks.get(e.track_id) if e.track_id else None
        views = []
        if e.detected is not None and e.latest is not None:
            views.append(self._wide(e.detected.station_id, e, e.latest, track))
        task = next((z for z in zoom if track and z.track_id == track.track_id), None)
        if task is not None and track is not None:
            views.append(self._zoom(task, track))
        threat = threats.get(e.track_id) if e.track_id else None
        stage = "acoustic" if e.detected is None else "camera"
        return CameraCue(
            cue_id=f"cue-{e.key}",
            picket_id=e.picket_id,
            heard_t=e.heard_t,
            stage="zoom" if len(views) == 2 else stage,
            cue_station_id=e.station_id,
            cue_bearing_deg=e.cue_azimuth_deg,
            detected_t=None if e.detected is None else e.detected.t,
            detected_by=None if e.detected is None else e.detected.station_id,
            track_id=e.track_id,
            alert_id=None if threat is None else threat.alert_id,
            views=views,
        )

    def _wide(
        self,
        station: str,
        e: _Engagement,
        latest: BearingDetection,
        track: Track | None,
    ) -> SimCameraView:
        """Pointed at the cue until a track links; then slewed onto the estimated track."""
        if track is not None:
            azimuth, elevation, range_m = bearing_to(
                self._stations[station], track.position_enu_m
            )
            pointing, target = (azimuth, elevation), (azimuth, elevation)
        else:
            range_m = None
            target = (latest.azimuth_deg, latest.elevation_deg)
            pointing = (self._azimuth_to_picket(station, e.picket_id), target[1])
        return SimCameraView(
            camera="wide",
            station_id=station,
            pointing_azimuth_deg=pointing[0],
            pointing_elevation_deg=pointing[1],
            fov_deg=2.0 * self._half_width_deg,
            seen_azimuth_deg=target[0],
            seen_elevation_deg=target[1],
            range_m=range_m,
            drawn_span_m=self._span_m,
        )

    def _zoom(self, task: ZoomTask, track: Track) -> SimCameraView:
        azimuth, elevation, range_m = bearing_to(
            self._stations[task.station_id], track.position_enu_m
        )
        return SimCameraView(
            camera="zoom",
            station_id=task.station_id,
            pointing_azimuth_deg=task.azimuth_deg,
            pointing_elevation_deg=task.elevation_deg,
            fov_deg=self._zoom_fov_deg,
            seen_azimuth_deg=azimuth,
            seen_elevation_deg=elevation,
            range_m=range_m,
            drawn_span_m=self._span_m,
        )


def _ground(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
