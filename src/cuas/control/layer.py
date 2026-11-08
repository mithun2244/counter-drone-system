"""The control layer: tracker, classifier, threat ranking, alerts, zoom and coverage in one stage.

It reads the gateway's accepted messages in order. Bearings within ``batch_window_s`` of each
other are handled together, so a batch is processed once a later message shows that its time
has passed. Sensor statuses arrive every second, which keeps time moving when nothing is seen.
Running every part in one stage, on the same batch, keeps the output deterministic.
"""

from cuas.config import SiteConfig, ZoneLabels
from cuas.control.alerts import AlertKeeper
from cuas.control.classify import Classifier
from cuas.control.coverage import CoverageMonitor
from cuas.control.scheduler import ZoomScheduler
from cuas.control.sectors import SectorTracker
from cuas.control.threat import ThreatRanker, rank
from cuas.control.tracker import SharedTracker
from cuas.schemas import BearingDetection, Message, PicketAlert, SensorStatus


class ControlLayer:
    def __init__(self, site: SiteConfig, labels: ZoneLabels) -> None:
        settings = site.tracker
        self._settings = settings
        self._stations = {s.id: s.position_enu_m for s in site.stations}
        self._pickets = {p.id: p.position_enu_m for p in site.pickets}
        self._picket_half_width_deg = site.picket_settings.bearing_error_deg
        reach = site.sensors[site.coverage.sensor].base_range_m[
            site.coverage.design_target
        ]
        loudest = max(e.hearing_radius_m for e in site.picket_settings.engines.values())
        self._tracker = SharedTracker(settings, self._stations)
        self._sectors = SectorTracker(settings.sector_lost_after_s)
        self._classifier = Classifier(
            site.classify,
            settings.gate_sigmas,
            self._stations,
            self._pickets,
            loudest,
            self._picket_half_width_deg,
        )
        self._ranker = ThreatRanker(site.threat, site.zones, labels)
        self._alerts = AlertKeeper(site.alerts)
        self._coverage = CoverageMonitor(
            site.coverage, site.zones, self._stations, reach
        )
        self._zoom = ZoomScheduler(
            site.zoom,
            site.zoom_per_station,
            self._stations,
            site.coverage.sensor,
            reach,
        )
        self._batch_t: float | None = None
        self._pending: list[BearingDetection] = []

    def ingest(self, message: Message) -> list[Message]:
        """Take one accepted message. Returns whatever it makes ready to publish."""
        out: list[Message] = []
        if (
            self._batch_t is not None
            and message.t - self._batch_t >= self._settings.batch_window_s
        ):
            out.extend(self._process())
        if self._batch_t is None:
            self._batch_t = message.t
        if isinstance(message, BearingDetection):
            self._pending.append(message)
        elif isinstance(message, PicketAlert):
            self._classifier.heard(message)
            out.append(
                self._sectors.report(
                    message.picket_id,
                    self._pickets[message.picket_id],
                    message.t,
                    message.bearing_deg,
                    self._picket_half_width_deg,
                )
            )
        elif isinstance(message, SensorStatus):
            self._coverage.report(message)
            self._zoom.report(message)
        return out

    def flush(self) -> list[Message]:
        """Process the last batch, once no more messages will come."""
        return self._process() if self._batch_t is not None else []

    def _process(self) -> list[Message]:
        t, bearings = self._batch_t, self._pending
        self._batch_t, self._pending = None, []
        tracks = self._tracker.update(t, bearings)
        out: list[Message] = [*tracks, *self._heard_only(t, bearings)]
        out.extend(self._sectors.expire(t))
        classified = self._classifier.update(t, tracks, bearings)
        raw = [self._ranker.assess(t, c) for c in classified]
        threats = rank(self._alerts.update(t, tracks, raw))
        out.extend(c.track_class for c in classified)
        out.extend(threats)
        out.extend(self._zoom.update(t, tracks, {a.track_id: a.score for a in threats}))
        if (coverage := self._coverage.update(t)) is not None:
            out.append(coverage)
        return out

    def _heard_only(self, t: float, bearings: list[BearingDetection]) -> list[Message]:
        """Wedges for bearings that cannot place a target and that no 3D track explains."""
        wedges: list[Message] = []
        for bearing in bearings:
            if (
                bearing.sensor in self._settings.position_sensors
                or bearing.sensor == "zoom"
            ):
                continue
            if self._tracker.accounts_for(bearing):
                continue  # heard, and already placed in 3D by the cameras
            wedges.append(
                self._sectors.report(
                    f"{bearing.station_id}.{bearing.sensor}",
                    self._stations[bearing.station_id],
                    t,
                    bearing.azimuth_deg,
                    self._settings.acoustic_sector_sigmas * bearing.sigma_deg,
                )
            )
        return wedges
