"""The evidence keeper: turns control output and operator requests into chain records.

It reads the control bus (tracks, classes, threat assessments) and the evidence bus (labels and
export requests), and publishes each record it appends on the evidence bus. Records:

- ``alert`` when an alert ID first appears, ``escalation`` when it first reaches red: a snapshot
  of the alert and its track history so far, and the recordings behind its look evidence;
- ``label`` for each operator label;
- ``export`` for each export request, and for every alert when the run ends: the hand-off
  package.

Without operator requests the records depend only on the control output, so the same run gives
the same chain byte for byte.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Literal

from cuas.bus import WILDCARD, Bus
from cuas.config import ZoneLabels
from cuas.evidence.handoff import (
    AlertSnapshot,
    ChainRef,
    Clip,
    HandoffPackage,
    HistoryPoint,
    LabelEntry,
)
from cuas.evidence.store import EVIDENCE_DIR, HANDOFF_DIR, EvidenceStore
from cuas.schemas import (
    EvidenceRecord,
    ExportRequest,
    Message,
    OperatorLabel,
    ThreatAssessment,
    Track,
    TrackClass,
)
from cuas.schemas.topics import EVIDENCE_RECORD

log = logging.getLogger(__name__)

# Where the recorder keeps recordings: WAV for a microphone, MP4 for every camera.
RECORDING_DIR = "station_{station}/{clip}{suffix}"
MICROPHONE = "acoustic"


@dataclass
class _Alert:
    threat: ThreatAssessment
    track_ids: list[str]
    record_hash: str = ""
    red: bool = False
    labels: list[LabelEntry] = field(default_factory=list)


class EvidenceKeeper:
    def __init__(self, store: EvidenceStore, run_id: str, labels: ZoneLabels) -> None:
        self._store = store
        self._run_id = run_id
        self._zone_labels = labels
        self._t = 0.0
        self._history: dict[str, list[HistoryPoint]] = {}
        self._classes: dict[str, TrackClass] = {}
        self._clips: dict[str, set[tuple[str, str]]] = {}
        self._alerts: dict[str, _Alert] = {}

    def ingest(self, message: Message) -> list[EvidenceRecord]:
        self._t = max(self._t, getattr(message, "t", self._t))
        if isinstance(message, Track) and message.status != "lost":
            x, y, z = message.position_enu_m
            point = HistoryPoint(
                track_id=message.track_id,
                t=message.t,
                x=x,
                y=y,
                z=z,
                n_stations=message.n_stations,
            )
            self._history.setdefault(message.track_id, []).append(point)
        elif isinstance(message, TrackClass):
            self._classes[message.track_id] = message
            seen = self._clips.setdefault(message.track_id, set())
            seen.update((s, ref.rpartition(":")[0]) for s, ref in message.looks.items())
        elif isinstance(message, ThreatAssessment) and message.alert_id is not None:
            return self._threat(message, message.alert_id)
        return []

    def handle(self, request: OperatorLabel | ExportRequest) -> EvidenceRecord | None:
        alert = self._alerts.get(request.alert_id)
        if alert is None:
            log.warning(
                "request %s names unknown alert %s",
                request.request_id,
                request.alert_id,
            )
            return None
        self._t = max(self._t, request.t)
        if isinstance(request, ExportRequest):
            return self._export(request.alert_id, alert, request.t, request.request_id)
        record = self._store.append(
            "label",
            request.t,
            request.alert_id,
            tuple(alert.track_ids),
            (),
            {"label": request.label},
            request.request_id,
        )
        alert.labels.append(
            LabelEntry(label=request.label, t=request.t, seq=record.seq)
        )
        return record

    def finish(self) -> list[EvidenceRecord]:
        """An export of every alert, in the order they were raised, as the run ends."""
        return [
            self._export(alert_id, alert, self._t, None)
            for alert_id, alert in self._alerts.items()
        ]

    def _threat(self, threat: ThreatAssessment, alert_id: str) -> list[EvidenceRecord]:
        alert = self._alerts.get(alert_id)
        if alert is None:
            alert = self._alerts[alert_id] = _Alert(threat, [threat.track_id])
            record = self._snapshot("alert", alert_id, alert)
            alert.record_hash, alert.red = record.record_hash, threat.level == "red"
            return [record]
        alert.threat = threat
        if threat.track_id not in alert.track_ids:
            alert.track_ids.append(threat.track_id)
        if threat.level == "red" and not alert.red:
            alert.red = True
            return [self._snapshot("escalation", alert_id, alert)]
        return []

    def _snapshot(
        self, kind: Literal["alert", "escalation"], alert_id: str, alert: _Alert
    ) -> EvidenceRecord:
        snapshot = self._summary(alert_id, alert, alert.threat.t)
        name = f"{EVIDENCE_DIR}/{self._store.next_seq:04d}-{kind}-{alert_id}.json"
        written = self._store.write(name, snapshot.model_dump_json(indent=1).encode())
        threat = alert.threat
        return self._store.append(
            kind,
            threat.t,
            alert_id,
            tuple(alert.track_ids),
            (written, *(clip.file for clip in snapshot.clips)),
            {"level": threat.level, "score": threat.score, "zone": threat.zone},
        )

    def _export(
        self, alert_id: str, alert: _Alert, t: float, request_id: str | None
    ) -> EvidenceRecord:
        head = self._store.head
        assert head is not None  # the alert's own record is in the chain
        package = HandoffPackage(
            run_id=self._run_id,
            exported_t=t,
            alert=self._summary(alert_id, alert, t),
            labels=list(alert.labels),
            alert_record_hash=alert.record_hash,
            chain_head=ChainRef(seq=head.seq, record_hash=head.record_hash),
        )
        name = f"{HANDOFF_DIR}/{alert_id}-{self._store.next_seq:04d}.json"
        written = self._store.write(name, package.model_dump_json(indent=1).encode())
        return self._store.append(
            "export",
            t,
            alert_id,
            tuple(alert.track_ids),
            (written,),
            {"reason": "operator" if request_id else "run end"},
            request_id,
        )

    def _summary(self, alert_id: str, alert: _Alert, t: float) -> AlertSnapshot:
        threat = alert.threat
        cls = self._classes.get(threat.track_id)
        history = sorted(
            (p for tid in alert.track_ids for p in self._history.get(tid, [])),
            key=lambda p: (p.t, p.track_id),
        )
        return AlertSnapshot(
            alert_id=alert_id,
            t=t,
            track_ids=list(alert.track_ids),
            level=threat.level,
            highest_level="red" if alert.red else "amber",
            score=threat.score,
            time_to_impact_s=threat.time_to_impact_s,
            zone_id=threat.zone,
            zone_label=None
            if threat.zone is None
            else getattr(self._zone_labels, threat.zone),
            reasons=list(threat.reasons),
            p_drone=None if cls is None else cls.p_drone,
            p_bird=None if cls is None else cls.p_bird,
            p_attack_drone=None if cls is None else cls.p_attack_drone,
            last_position=history[-1] if history else None,
            track_history=history,
            clips=self._clip_files(alert.track_ids),
        )

    def _clip_files(self, track_ids: list[str]) -> list[Clip]:
        seen = sorted({c for tid in track_ids for c in self._clips.get(tid, set())})
        clips = []
        for source, clip in seen:
            station, _, sensor = source.partition(".")
            suffix = ".wav" if sensor == MICROPHONE else ".mp4"
            path = RECORDING_DIR.format(station=station, clip=clip, suffix=suffix)
            ref = self._store.ref(path)
            if ref is not None:
                clips.append(Clip(source=source, file=ref))
        return clips


def start_keeper(
    keeper: EvidenceKeeper, control: Bus, evidence: Bus
) -> asyncio.Task[None]:
    """Subscribe now, before anything is published. Runs until the control bus closes, then
    exports every alert and closes the evidence bus. Requests still queued then are dropped,
    and whoever sent them sees the bus close."""
    return asyncio.create_task(
        _keep(
            keeper, control.subscribe(WILDCARD), evidence.subscribe(WILDCARD), evidence
        )
    )


async def _keep(
    keeper: EvidenceKeeper,
    control: AsyncIterator[Message],
    requests: AsyncIterator[Message],
    evidence: Bus,
) -> None:
    async def answer() -> None:
        async for request in requests:
            if isinstance(request, OperatorLabel | ExportRequest):
                try:
                    record = keeper.handle(request)
                except Exception:  # one bad request must not stop the answers (logged)
                    log.exception("could not answer %s", request.request_id)
                    continue  # its sender times out with the reason in the server console
                if (
                    record is not None
                ):  # publishing never yields, so no record is half-sent
                    await evidence.publish(EVIDENCE_RECORD, record)

    answering = asyncio.create_task(answer())
    async for message in control:
        for record in keeper.ingest(message):
            await evidence.publish(EVIDENCE_RECORD, record)
    answering.cancel()
    with suppress(asyncio.CancelledError):
        await answering
    for record in keeper.finish():
        await evidence.publish(EVIDENCE_RECORD, record)
    await evidence.close()
