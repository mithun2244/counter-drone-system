"""The evidence keeper on hand-made messages, through its bus wiring, and on a recorded run."""

import hashlib
from pathlib import Path

import pytest

from cuas.bus import InProcessBus
from cuas.config import ZoneLabels
from cuas.evidence.handoff import AlertSnapshot, ChainRef, HandoffPackage, LabelEntry
from cuas.evidence.keeper import EvidenceKeeper, start_keeper
from cuas.evidence.store import EvidenceStore
from cuas.evidence.verify import verify_chain
from cuas.schemas import (
    ClueEvidence,
    ExportRequest,
    FileRef,
    OperatorLabel,
    ThreatAssessment,
    Track,
    TrackClass,
)
from cuas.schemas.topics import EVIDENCE_RECORD, OPERATOR_LABEL, THREAT, TRACK
from cuas.sim.scenario import load_scenario
from cuas.station.recorder import Recorder

LABELS = ZoneLabels(critical="Pitch", important="Grounds", perimeter="Perimeter")
COV = tuple(tuple(1.0 if i == j else 0.0 for j in range(6)) for i in range(6))


def track(track_id: str, t: float, n: int = 3) -> Track:
    return Track(
        track_id=track_id,
        t=t,
        position_enu_m=(10.0 * t, 500.0, 80.0),
        velocity_mps=(10.0, 0.0, 0.0),
        covariance=COV,
        n_stations=n,
        status="confirmed",
    )


def threat(
    track_id: str, t: float, level: str, alert_id: str | None
) -> ThreatAssessment:
    return ThreatAssessment(
        track_id=track_id,
        t=t,
        score=0.8,
        level=level,
        zone="critical",
        time_to_impact_s=20.0,
        reasons=("seen hovering",),
        alert_id=alert_id,
    )


@pytest.fixture
def keeper(tmp_path: Path) -> EvidenceKeeper:
    return EvidenceKeeper(EvidenceStore(tmp_path), "run-1", LABELS)


def feed(keeper: EvidenceKeeper, *messages) -> list:
    return [record for m in messages for record in keeper.ingest(m)]


def read(model, tmp_path: Path, ref: FileRef):
    return model.model_validate_json((tmp_path / ref.path).read_bytes())


def test_an_alert_is_recorded_when_raised_and_again_when_it_first_turns_red(
    keeper: EvidenceKeeper, tmp_path: Path
) -> None:
    records = feed(
        keeper,
        track("trk-1", 1.0),
        threat("trk-1", 1.0, "info", None),  # no alert yet: nothing to record
        track("trk-1", 1.2),
        threat("trk-1", 1.2, "amber", "alert-1"),
        threat("trk-1", 1.4, "amber", "alert-1"),
        threat("trk-1", 1.6, "red", "alert-1"),
        threat("trk-1", 1.8, "amber", "alert-1"),
        threat("trk-1", 2.0, "red", "alert-1"),
    )
    assert [(r.kind, r.t, r.seq) for r in records] == [
        ("alert", 1.2, 1),
        ("escalation", 1.6, 2),
    ]
    assert records[0].files[0].path == "evidence/0001-alert-alert-1.json"
    raised = read(AlertSnapshot, tmp_path, records[0].files[0])
    turned = read(AlertSnapshot, tmp_path, records[1].files[0])
    assert (raised.level, raised.highest_level) == ("amber", "amber")
    assert (turned.level, turned.highest_level, turned.zone_label) == (
        "red",
        "red",
        "Pitch",
    )
    assert [p.t for p in turned.track_history] == [1.0, 1.2]
    assert turned.last_position == turned.track_history[-1]
    assert records[1].details == {"level": "red", "score": 0.8, "zone": "critical"}


def test_a_track_picked_up_again_joins_its_alert_history(
    keeper: EvidenceKeeper, tmp_path: Path
) -> None:
    records = feed(
        keeper,
        track("trk-1", 1.0),
        threat("trk-1", 1.0, "amber", "alert-1"),
        track("trk-2", 5.0, n=0),
        threat("trk-2", 5.0, "red", "alert-1"),
    )
    assert records[1].track_ids == ("trk-1", "trk-2")
    snapshot = read(AlertSnapshot, tmp_path, records[1].files[0])
    assert [(p.track_id, p.n_stations) for p in snapshot.track_history] == [
        ("trk-1", 3),
        ("trk-2", 0),
    ]


def test_the_recordings_behind_its_looks_are_listed_with_their_hashes(
    keeper: EvidenceKeeper, tmp_path: Path
) -> None:
    Recorder(tmp_path).save("st1", "abcdef0123456789", ".mp4", b"clip")
    looks = {"st1.rgb": "abcdef0123456789:4", "st2.zoom": "0123456789abcdef:1"}
    classed = TrackClass(
        track_id="trk-1",
        t=1.0,
        p_drone=0.9,
        p_bird=0.1,
        p_attack_drone=0.0,
        evidence=ClueEvidence(look=0.9),
        looks=looks,
    )
    records = feed(
        keeper, track("trk-1", 1.0), classed, threat("trk-1", 1.0, "red", "a")
    )
    clip = FileRef(
        path="station_st1/abcdef0123456789.mp4",
        sha256=hashlib.sha256(b"clip").hexdigest(),
    )
    assert records[0].files[1:] == (clip,)  # the st2 recording was never kept: skipped
    snapshot = read(AlertSnapshot, tmp_path, records[0].files[0])
    assert [(c.source, c.file) for c in snapshot.clips] == [("st1.rgb", clip)]
    assert (snapshot.p_drone, snapshot.p_bird) == (0.9, 0.1)


def test_labels_and_exports_answer_their_requests(
    keeper: EvidenceKeeper, tmp_path: Path
) -> None:
    (raised,) = feed(
        keeper, track("trk-1", 1.0), threat("trk-1", 1.0, "red", "alert-1")
    )
    label = keeper.handle(
        OperatorLabel(alert_id="alert-1", label="dismiss", t=5.0, request_id="req-1")
    )
    assert label is not None
    assert (label.kind, label.request_id, label.details, label.files) == (
        "label",
        "req-1",
        {"label": "dismiss"},
        (),
    )
    export = keeper.handle(ExportRequest(alert_id="alert-1", t=6.0, request_id="req-2"))
    assert export is not None and export.files[0].path == "handoff/alert-1-0003.json"
    package = read(HandoffPackage, tmp_path, export.files[0])
    assert package.mock and package.run_id == "run-1" and package.exported_t == 6.0
    assert package.labels == [LabelEntry(label="dismiss", t=5.0, seq=2)]
    assert package.alert_record_hash == raised.record_hash
    assert package.chain_head == ChainRef(seq=2, record_hash=label.record_hash)
    assert export.details == {"reason": "operator"}
    unknown = OperatorLabel(alert_id="alert-9", label="confirm", t=7.0, request_id="r")
    assert keeper.handle(unknown) is None


def test_every_alert_is_exported_when_the_run_ends(keeper: EvidenceKeeper) -> None:
    feed(
        keeper,
        track("trk-1", 1.0),
        threat("trk-1", 1.0, "amber", "alert-1"),
        track("trk-2", 2.0),
        threat("trk-2", 2.0, "red", "alert-2"),
        track("trk-2", 9.0),
    )
    exports = keeper.finish()
    assert [(r.kind, r.alert_id, r.t, r.details) for r in exports] == [
        ("export", "alert-1", 9.0, {"reason": "run end"}),
        ("export", "alert-2", 9.0, {"reason": "run end"}),
    ]


async def test_through_its_buses_it_answers_requests_then_exports_and_closes(
    tmp_path: Path,
) -> None:
    control, evidence = InProcessBus(), InProcessBus()
    keeper = EvidenceKeeper(EvidenceStore(tmp_path), "run-1", LABELS)
    task = start_keeper(keeper, control, evidence)
    records = evidence.subscribe(EVIDENCE_RECORD)
    await control.publish(TRACK, track("trk-1", 1.0))
    await control.publish(THREAT, threat("trk-1", 1.0, "red", "alert-1"))
    raised = await anext(records)
    request = OperatorLabel(
        alert_id="alert-1", label="confirm", t=2.0, request_id="req-1"
    )
    await evidence.publish(OPERATOR_LABEL, request)
    labelled = await anext(records)
    await control.close()
    await task
    rest = [r async for r in records]  # ends: the keeper closed the evidence bus
    assert (raised.kind, labelled.kind, labelled.request_id) == (
        "alert",
        "label",
        "req-1",
    )
    assert [r.kind for r in rest] == ["export"]
    assert verify_chain(tmp_path).problems == []


def files_of(run_dir: Path) -> dict[str, bytes]:
    return {
        p.relative_to(run_dir).as_posix(): p.read_bytes()
        for p in sorted(run_dir.rglob("*"))
        if p.is_file()
    }


async def test_the_same_run_gives_the_same_evidence_byte_for_byte(
    record_pipeline, tmp_path: Path, config_dir: Path
) -> None:
    _, _, controlled, _ = await record_pipeline("s1", seed=7)
    labels = load_scenario(config_dir, "s1").metadata.zone_labels
    for name in ("first", "second"):
        keeper = EvidenceKeeper(EvidenceStore(tmp_path / name), "run-s1", labels)
        for message in controlled:
            keeper.ingest(message)
        keeper.finish()
    first, second = files_of(tmp_path / "first"), files_of(tmp_path / "second")
    assert len(first) > 3 and first == second
