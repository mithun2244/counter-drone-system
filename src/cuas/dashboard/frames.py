"""Builds the dashboard's frames from bus messages (docs/dashboard_contract.md).

It reads accepted observations (statuses, picket alerts, bearings) and control-layer output, and
emits a snapshot each time simulated time passes the next ``frame_period_s`` mark. It sees bus
messages only, never ground truth. The same message sequence always gives the same frames.
"""

import heapq
from collections import deque
from collections.abc import Iterable, Sequence

from cuas.config import DashboardSettings, ScenarioMetadata, SiteConfig, ZoneLabels
from cuas.dashboard.contract import (
    AlertCard,
    Bounds,
    CoverageView,
    EvidenceHead,
    Frame,
    LookRef,
    PicketHeard,
    PicketView,
    PreAlert,
    Ray,
    RunInfo,
    ScenarioChoice,
    SensorView,
    SiteMap,
    SiteProfile,
    StationView,
    TrackView,
    ZoneView,
    ZoomView,
)
from cuas.schemas import (
    BearingDetection,
    CoverageStatus,
    EvidenceRecord,
    Message,
    PicketAlert,
    SectorTrack,
    SensorStatus,
    ThreatAssessment,
    Track,
    TrackClass,
    ZoomTask,
)

COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
EARLY = 1e-9
FULL_VISIBILITY = 1.0
CLIP_URL = "/api/clips/{station}/{clip}"


def compass(bearing_deg: float) -> str:
    return COMPASS[round(bearing_deg / 45.0) % len(COMPASS)]


def site_map(site: SiteConfig, labels: ZoneLabels, margin_fraction: float) -> SiteMap:
    zones = sorted(site.zones, key=lambda z: z.weight)  # outermost first
    points = [p for z in site.zones for p in z.polygon_enu_m]
    points += [s.position_enu_m[:2] for s in (*site.stations, *site.pickets)]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    margin = margin_fraction * max(max(xs) - min(xs), max(ys) - min(ys))
    return SiteMap(
        bounds=Bounds(
            min_x=min(xs) - margin,
            min_y=min(ys) - margin,
            max_x=max(xs) + margin,
            max_y=max(ys) + margin,
        ),
        zones=[
            ZoneView(
                zone_id=z.id,
                label=getattr(labels, z.id),
                weight=z.weight,
                polygon=[(x, y) for x, y in z.polygon_enu_m],
            )
            for z in zones
        ],
        stations=[
            StationView(
                station_id=s.id,
                x=s.position_enu_m[0],
                y=s.position_enu_m[1],
                z=s.position_enu_m[2],
            )
            for s in site.stations
        ],
        pickets=[
            PicketView(picket_id=p.id, x=p.position_enu_m[0], y=p.position_enu_m[1])
            for p in site.pickets
        ],
    )


def profiles(scenarios: Sequence[ScenarioMetadata]) -> list[SiteProfile]:
    """One saved site profile per venue, with the scenarios that run there."""
    by_venue: dict[str, list[ScenarioMetadata]] = {}
    for meta in sorted(scenarios, key=lambda m: m.id):
        by_venue.setdefault(meta.venue, []).append(meta)
    out = []
    for venue, metas in by_venue.items():
        if any(m.zone_labels != metas[0].zone_labels for m in metas):
            raise ValueError(f"{venue}: scenarios disagree on zone labels")
        out.append(
            SiteProfile(
                profile_id=venue.lower().replace(" ", "-"),
                venue=venue,
                zone_labels=metas[0].zone_labels.model_dump(),
                scenarios=[
                    ScenarioChoice(scenario_id=m.id, title=m.title) for m in metas
                ],
            )
        )
    return out


def run_info(
    run_id: str,
    meta: ScenarioMetadata,
    known: Sequence[SiteProfile],
    site: SiteConfig,
    seed: int,
    duration_s: float,
    recorded_media: bool,
) -> RunInfo:
    """A run as it starts: running at 1x, with the map of its site."""
    return RunInfo(
        run_id=run_id,
        profile_id=next(p.profile_id for p in known if p.venue == meta.venue),
        scenario_id=meta.id,
        title=meta.title,
        venue=meta.venue,
        seed=seed,
        duration_s=duration_s,
        recorded_media=recorded_media,
        zoom_per_station=site.zoom_per_station,
        state="running",
        speed=1.0,
        site=site_map(site, meta.zone_labels, site.dashboard.map_margin_fraction),
    )


class FrameBuilder:
    def __init__(self, run_id: str, site: SiteConfig, labels: ZoneLabels) -> None:
        self._run_id = run_id
        self._settings: DashboardSettings = site.dashboard
        self._labels = labels
        coverage = site.coverage
        self._reach_sensor = coverage.sensor
        self._base_reach_m = site.sensors[coverage.sensor].base_range_m[
            coverage.design_target
        ]
        self._stations = {s.id: s.position_enu_m for s in site.stations}
        self._look_period_s = site.station_ai.look.period_s
        self._next_k = 0
        self._tracks: dict[str, Track] = {}
        self._trails: dict[str, deque[tuple[float, float, float]]] = {}
        self._classes: dict[str, TrackClass] = {}
        self._threats: list[ThreatAssessment] = []
        self._sectors: dict[str, tuple[SectorTrack, float]] = {}
        self._picket_alerts: deque[PicketAlert] = deque()
        self._rays: list[BearingDetection] = []
        self._zoom: dict[tuple[str, str], ZoomTask] = {}
        self._coverage: CoverageStatus | None = None
        self._sensors: dict[str, SensorStatus] = {}
        self._head: EvidenceHead | None = None
        self._records: dict[str, int] = {}
        self._operator_labels: dict[str, str] = {}

    def ingest(self, message: Message) -> list[Frame]:
        """Take one message. Returns the frames for every mark it shows has passed."""
        t = getattr(message, "t", None)
        frames = [] if t is None else self.advance(t)
        self._apply(message)
        return frames

    def advance(self, t: float) -> list[Frame]:
        """The frames for every mark before ``t``. A live run calls it on the clock, because
        simulated time also passes while nothing is heard."""
        frames = []
        while t > self._mark() + EARLY:
            frames.append(self._frame(self._mark()))
            self._next_k += 1
        return frames

    def again(self) -> Frame | None:
        """The latest frame once more, with what changed since: for a live run, evidence the
        operator wrote while the clock was paused. ``None`` before the first frame."""
        if self._next_k == 0:
            return None
        return self._frame((self._next_k - 1) * self._settings.frame_period_s)

    def flush(self) -> Frame:
        """The last frame, once no more messages will come."""
        frame = self._frame(self._mark())
        self._next_k += 1
        return frame

    def _mark(self) -> float:
        return self._next_k * self._settings.frame_period_s

    def _apply(self, message: Message) -> None:
        if isinstance(message, Track):
            self._track(message)
        elif isinstance(message, TrackClass):
            self._classes[message.track_id] = message
        elif isinstance(message, ThreatAssessment):
            if self._threats and self._threats[0].t != message.t:
                self._threats = []
            self._threats.append(message)
        elif isinstance(message, SectorTrack):
            if message.status == "lost":
                self._sectors.pop(message.sector_id, None)
            else:
                first = self._sectors.get(message.sector_id, (message, message.t))[1]
                self._sectors[message.sector_id] = (message, first)
        elif isinstance(message, CoverageStatus):
            self._coverage = message
        elif isinstance(message, ZoomTask):
            self._zoom[(message.station_id, message.camera_id)] = message
        elif isinstance(message, SensorStatus):
            self._sensors[message.sensor_id] = message
        elif isinstance(message, PicketAlert):
            self._picket_alerts.append(message)
        elif isinstance(message, EvidenceRecord):
            self._evidence(message)
        elif isinstance(message, BearingDetection):
            if self._rays and self._rays[0].t != message.t:
                self._rays = []
            self._rays.append(message)

    def _evidence(self, record: EvidenceRecord) -> None:
        self._head = EvidenceHead(seq=record.seq, record_hash=record.record_hash)
        self._records[record.alert_id] = self._records.get(record.alert_id, 0) + 1
        label = record.details.get("label")
        if record.kind == "label" and isinstance(label, str):
            self._operator_labels[record.alert_id] = label

    def _track(self, track: Track) -> None:
        if track.status == "lost":
            for store in (self._tracks, self._trails, self._classes):
                store.pop(track.track_id, None)
            return
        self._tracks[track.track_id] = track
        trail = self._trails.setdefault(track.track_id, deque())
        x, y, _ = track.position_enu_m
        if not trail or track.t - trail[-1][0] >= self._settings.trail_step_s - EARLY:
            trail.append((track.t, x, y))

    def _frame(self, t: float) -> Frame:
        settings = self._settings
        for trail in self._trails.values():
            while trail and trail[0][0] < t - settings.trail_s - EARLY:
                trail.popleft()
        while (
            self._picket_alerts
            and self._picket_alerts[0].t < t - settings.picket_flash_s - EARLY
        ):
            self._picket_alerts.popleft()
        threats = {a.track_id: a for a in self._threats if a.track_id in self._tracks}
        return Frame(
            run_id=self._run_id,
            t=t,
            tracks=[
                self._track_view(tr, threats.get(tid))
                for tid, tr in sorted(self._tracks.items())
            ],
            alerts=[
                self._card(a, a.alert_id)
                for a in self._threats
                if a.alert_id is not None and a.track_id in self._tracks
            ],
            pre_alerts=[
                self._pre_alert(s, first) for s, first in self._sectors.values()
            ],
            pickets_heard=[
                PicketHeard(picket_id=a.picket_id, t=a.t) for a in self._picket_alerts
            ],
            rays=[
                Ray(
                    station_id=b.station_id,
                    sensor=b.sensor,
                    azimuth_deg=b.azimuth_deg,
                    elevation_deg=b.elevation_deg,
                    sigma_deg=b.sigma_deg,
                )
                for b in self._rays
            ],
            zoom=[
                ZoomView(
                    station_id=z.station_id,
                    camera_id=z.camera_id,
                    track_id=z.track_id,
                    azimuth_deg=z.azimuth_deg,
                    elevation_deg=z.elevation_deg,
                )
                for _, z in sorted(self._zoom.items())
                if z.track_id in self._tracks
            ],
            coverage=self._coverage_view(),
            sensors=[
                SensorView(
                    sensor_id=s.sensor_id, ok=s.ok, visibility=s.visibility_factor
                )
                for _, s in sorted(self._sensors.items())
            ],
            evidence_head=self._head,
        )

    def _track_view(self, track: Track, threat: ThreatAssessment | None) -> TrackView:
        x, y, z = track.position_enu_m
        vx, vy, _ = track.velocity_mps
        cls = self._classes.get(track.track_id)
        return TrackView(
            track_id=track.track_id,
            status="confirmed" if track.status == "confirmed" else "tentative",
            x=x,
            y=y,
            z=z,
            vx=vx,
            vy=vy,
            n_stations=track.n_stations,
            coasting=track.n_stations == 0,
            trail=list(self._trails.get(track.track_id, ())),
            level=None if threat is None else threat.level,
            alert_id=None if threat is None else threat.alert_id,
            p_drone=None if cls is None else cls.p_drone,
            p_attack_drone=None if cls is None else cls.p_attack_drone,
            p_bird=None if cls is None else cls.p_bird,
        )

    def _card(self, threat: ThreatAssessment, alert_id: str) -> AlertCard:
        track = self._tracks[threat.track_id]
        cls = self._classes.get(threat.track_id)
        p_drone = 0.0 if cls is None else cls.p_drone
        p_attack = 0.0 if cls is None else cls.p_attack_drone
        threshold = self._settings.class_threshold
        if p_attack >= threshold:
            class_key, confidence = "attack", p_attack
        else:
            class_key = "drone" if p_drone >= threshold else "unclassified"
            confidence = p_drone
        tti = threat.time_to_impact_s
        approach = "none" if tti is None else ("inside" if tti == 0.0 else "heading_to")
        return AlertCard(
            alert_id=alert_id,
            track_id=threat.track_id,
            level=threat.level,
            score=threat.score,
            tti_s=tti,
            zone_id=threat.zone,
            zone_label=None
            if threat.zone is None
            else getattr(self._labels, threat.zone),
            approach=approach,
            class_key=class_key,
            confidence=confidence,
            n_stations=track.n_stations,
            coasting=track.n_stations == 0,
            reasons=list(threat.reasons),
            label=self._operator_labels.get(alert_id),
            evidence_records=self._records.get(alert_id, 0),
            looks=[] if cls is None else self._looks(cls),
        )

    def _looks(self, cls: TrackClass) -> list[LookRef]:
        """A snapshot ref is ``<clip id>:<look index>``; looks are ``look period`` apart."""
        out = []
        for source, ref in cls.looks.items():
            station = source.split(".")[0]
            clip, _, index = ref.rpartition(":")
            out.append(
                LookRef(
                    source=source,
                    clip_url=CLIP_URL.format(station=station, clip=clip),
                    at_s=int(index) * self._look_period_s,
                )
            )
        return out

    def _pre_alert(self, sector: SectorTrack, first_t: float) -> PreAlert:
        x, y, _ = sector.origin_enu_m
        return PreAlert(
            sector_id=sector.sector_id,
            sensor_id=sector.sensor_id,
            x=x,
            y=y,
            bearing_deg=sector.bearing_deg,
            compass=compass(sector.bearing_deg),
            half_width_deg=sector.half_width_deg,
            first_t=first_t,
            last_t=sector.t,
            reports=sector.reports,
        )

    def _coverage_view(self) -> CoverageView | None:
        if self._coverage is None:
            return None
        reach = {
            station: self._base_reach_m
            * getattr(
                self._sensors.get(f"{station}.{self._reach_sensor}"),
                "visibility_factor",
                FULL_VISIBILITY,
            )
            for station in sorted(self._stations)
        }
        return CoverageView(
            pct=self._coverage.coverage_pct,
            warning=self._coverage.warning,
            reach_m=reach,
        )


def replay(
    builder: FrameBuilder, accepted: Iterable[Message], controlled: Iterable[Message]
) -> list[Frame]:
    """Frames from recorded bus traffic, merged by time: the deterministic path for samples."""
    merged = heapq.merge(accepted, controlled, key=lambda m: getattr(m, "t", 0.0))
    frames = [frame for message in merged for frame in builder.ingest(message)]
    return [*frames, builder.flush()]
