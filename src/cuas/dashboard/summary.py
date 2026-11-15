"""Run history from dashboard observations; never simulation ground truth."""

from typing import Any

from cuas.dashboard.contract import EvidenceEvent, Frame
from cuas.schemas import (
    BearingDetection,
    Message,
    PicketAlert,
    ThreatAssessment,
    Track,
    TrackClass,
)


class RunSummary:
    def __init__(self) -> None:
        self.latest: dict[str, Any] | None = None
        self.tracks: dict[str, dict[str, Any]] = {}
        self.alert_tracks: set[str] = set()
        self.evidence_count = 0
        self.elapsed = 0.0
        self.active_alerts = 0
        self.snapshot_ref: str | None = None

    def ingest(self, message: Message) -> None:
        if isinstance(message, BearingDetection):
            self.detect(message.t, f"{message.station_id}.{message.sensor}", None)
            if (
                self.latest
                and self.latest["t"] == message.t
                and self.latest["sensor"] == f"{message.station_id}.{message.sensor}"
            ):
                self.snapshot_ref = message.snapshot_ref
            if (
                self.latest
                and self.latest["t"] == message.t
                and self.latest["sensor"] == f"{message.station_id}.{message.sensor}"
                and message.class_probs
            ):
                self.latest["classification"] = max(
                    message.class_probs, key=message.class_probs.get
                )
        elif isinstance(message, PicketAlert):
            self.detect(message.t, message.picket_id, None)
        elif isinstance(message, Track):
            self.tracks.setdefault(message.track_id, {})["position"] = {
                "x": message.position_enu_m[0],
                "y": message.position_enu_m[1],
                "z": message.position_enu_m[2],
                "t": message.t,
            }
        elif isinstance(message, TrackClass):
            for sensor, heard in message.heard.items():
                if (
                    self.latest
                    and heard.t == self.latest["t"]
                    and sensor == self.latest["sensor"]
                ):
                    self.latest["track_id"] = message.track_id
            if (
                self.latest
                and self.snapshot_ref
                and message.looks.get(self.latest["sensor"]) == self.snapshot_ref
            ):
                self.latest["track_id"] = message.track_id
        elif isinstance(message, ThreatAssessment):
            if message.alert_id is not None:
                self.alert_tracks.add(message.track_id)
            entry = self.tracks.setdefault(message.track_id, {})
            levels = {"info": 0, "amber": 1, "red": 2}
            if levels[message.level] >= levels.get(entry.get("peak_level"), -1):
                entry["peak_level"] = message.level

    def evidence(self, event: EvidenceEvent) -> None:
        self.evidence_count = max(self.evidence_count, event.seq)

    def frame(self, frame: Frame) -> None:
        self.elapsed = frame.t
        self.active_alerts = len(frame.alerts)
        if frame.evidence_head:
            self.evidence_count = max(self.evidence_count, frame.evidence_head.seq)
        for track in frame.tracks:
            entry = self.tracks.setdefault(track.track_id, {})
            entry["position"] = {"x": track.x, "y": track.y, "z": track.z, "t": frame.t}
            for heard in track.heard:
                self.detect(heard.t, heard.sensor_id, track.track_id)
        for alert in frame.alerts:
            self.alert_tracks.add(alert.track_id)
            entry = self.tracks.setdefault(alert.track_id, {})
            entry["classification"] = alert.class_key
            levels = {"info": 0, "amber": 1, "red": 2}
            if levels[alert.level] >= levels.get(entry.get("peak_level"), -1):
                entry["peak_level"] = alert.level
        for cue in frame.cues:
            if cue.detected_t is not None:
                self.detect(cue.detected_t, cue.detected_by, cue.track_id)
            if cue.current_rgb_t is not None:
                self.detect(
                    cue.current_rgb_t, "Wide RGB (station unavailable)", cue.track_id
                )
        for sector in frame.pre_alerts:
            self.detect(sector.last_t, sector.sensor_id, None)

    def detect(self, t: float, sensor: str | None, track_id: str | None) -> None:
        if (
            self.latest is None
            or t > self.latest["t"]
            or t == self.latest["t"]
            and self.latest["track_id"] is None
            and track_id
        ):
            self.latest = {"t": t, "sensor": sensor, "track_id": track_id}

    def result(self) -> dict[str, Any]:
        latest = None
        if self.latest:
            latest = {**self.latest, **self.tracks.get(self.latest["track_id"], {})}
        positions = [
            {**entry["position"], "track_id": track_id}
            for track_id, entry in self.tracks.items()
            if "position" in entry
        ]
        return {
            "elapsed_s": self.elapsed,
            "active_alerts": self.active_alerts,
            "unique_alert_tracks": len(self.alert_tracks),
            "evidence_records": self.evidence_count,
            "latest_detection": latest,
            "last_position": max(positions, key=lambda p: p["t"], default=None),
        }
