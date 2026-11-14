import re
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from cuas import schemas
from cuas.schemas import (
    BearingDetection,
    ClueEvidence,
    CoverageStatus,
    EvidenceRecord,
    ExportRequest,
    FileRef,
    Message,
    OperatorLabel,
    PicketAlert,
    RejectedMessage,
    SectorTrack,
    SensorStatus,
    ThreatAssessment,
    Track,
    TrackClass,
    ZoomTask,
)

ARCHITECTURE = Path(__file__).resolve().parents[2] / "docs" / "architecture.md"
HASH = "a" * 64

SAMPLES: list[Message] = [
    SensorStatus(sensor_id="st1.rgb", ok=True, visibility_factor=0.5, t=1.0),
    BearingDetection(
        station_id="st1",
        sensor="rgb",
        t=1.2,
        azimuth_deg=359.5,
        elevation_deg=1.5,
        sigma_deg=0.05,
    ),
    PicketAlert(
        picket_id="pk4",
        t=2.0,
        bearing_deg=135.0,
        loudness=0.4,
        engine_type_probs={"piston": 0.8, "electric": 0.2},
    ),
    Track(
        track_id="trk1",
        t=3.0,
        position_enu_m=(1.0, 2.0, 3.0),
        velocity_mps=(4.0, 5.0, 6.0),
        covariance=((1.0, 0.0), (0.0, 1.0)),
        n_stations=2,
        status="confirmed",
    ),
    TrackClass(
        track_id="trk1",
        t=3.0,
        p_drone=0.9,
        p_bird=0.1,
        p_attack_drone=0.8,
        evidence=ClueEvidence(look=0.9, move=0.8),
    ),
    ThreatAssessment(
        track_id="trk1",
        t=3.0,
        score=0.7,
        level="red",
        zone="critical",
        time_to_impact_s=24.0,
        reasons=("fast straight flight",),
        alert_id="alert-1",
    ),
    ZoomTask(
        station_id="st1",
        t=3.0,
        camera_id="z1",
        track_id="trk1",
        azimuth_deg=10.0,
        elevation_deg=2.0,
    ),
    EvidenceRecord(
        seq=1,
        kind="alert",
        t=3.0,
        alert_id="alert-1",
        track_ids=("trk1",),
        files=(FileRef(path="evidence/0001-alert-alert-1.json", sha256=HASH),),
        details={"level": "amber", "score": 0.6, "zone": None},
        prev_hash=None,
        record_hash=HASH,
    ),
    OperatorLabel(alert_id="alert-1", label="confirm", t=4.0, request_id="req-1"),
    ExportRequest(alert_id="alert-1", t=5.0, request_id="req-2"),
    RejectedMessage(reason="unknown sensor", raw="{}"),
    SectorTrack(
        sector_id="sec-1",
        t=4.0,
        sensor_id="pk4",
        origin_enu_m=(2121.3, -2121.3, 3.0),
        bearing_deg=300.0,
        half_width_deg=20.0,
        reports=1,
        status="active",
    ),
    CoverageStatus(t=5.0, coverage_pct=55.0, warning=True),
]
SAMPLE_IDS = [type(sample).__name__ for sample in SAMPLES]


def architecture_messages() -> dict[str, list[str]]:
    """Message names and key fields, parsed from the table in architecture.md section 4."""
    rows = re.findall(
        r"^\| `(\w+)` \| [^|]+ \| ([^|]+) \|",
        ARCHITECTURE.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    return {
        name: [field.strip() for field in re.sub(r"\(.*?\)", "", fields).split(",")]
        for name, fields in rows
    }


def test_every_architecture_message_and_key_field_has_a_schema() -> None:
    messages = architecture_messages()
    assert len(messages) == 13
    for name, fields in messages.items():
        model = getattr(schemas, name)
        assert issubclass(model, Message)
        missing = [field for field in fields if field not in model.model_fields]
        assert not missing, f"{name} is missing {missing}"


def test_samples_cover_every_message() -> None:
    assert set(SAMPLE_IDS) == set(architecture_messages())


@pytest.mark.parametrize("sample", SAMPLES, ids=SAMPLE_IDS)
def test_json_round_trip_is_exact(sample: Message) -> None:
    assert type(sample).model_validate_json(sample.model_dump_json()) == sample


@pytest.mark.parametrize("sample", SAMPLES, ids=SAMPLE_IDS)
def test_unknown_fields_are_rejected(sample: Message) -> None:
    with pytest.raises(ValidationError):
        type(sample).model_validate({**sample.model_dump(), "target_id": "quad-1"})


@pytest.mark.parametrize("sample", SAMPLES, ids=SAMPLE_IDS)
def test_messages_are_frozen(sample: Message) -> None:
    field = next(iter(type(sample).model_fields))
    with pytest.raises(ValidationError):
        setattr(sample, field, "changed")


def models_in_schemas() -> list[type[BaseModel]]:
    return [
        value
        for value in vars(schemas).values()
        if isinstance(value, type) and issubclass(value, BaseModel)
    ]


def test_no_schema_has_a_ground_truth_field() -> None:
    assert (
        len(models_in_schemas()) == 18
    )  # 14 messages, ClueEvidence, FileRef, HeardBearing and the Message base
    for model in models_in_schemas():
        for field in model.model_fields:
            assert not re.search("target|true|truth", field), (
                f"{model.__name__}.{field}"
            )


def bearing_with(**changes: object) -> dict[str, object]:
    return {**SAMPLES[1].model_dump(), **changes}


@pytest.mark.parametrize(
    "changes",
    [
        {"azimuth_deg": 360.0},
        {"azimuth_deg": -0.1},
        {"azimuth_deg": float("nan")},
        {"elevation_deg": 90.5},
        {"sigma_deg": 0.0},
        {"t": -1.0},
        {"t": "1.0"},
        {"sensor": "radar"},
        {"class_probs": {"drone": 1.5}},
    ],
    ids=str,
)
def test_bearing_rejects_bad_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BearingDetection.model_validate(bearing_with(**changes))


def test_a_sector_track_cannot_carry_a_3d_point() -> None:
    fields = set(SectorTrack.model_fields)
    assert not {f for f in fields if re.search("position|range|elevation|velocity", f)}


@pytest.mark.parametrize("field", ["prev_hash", "record_hash", "files"])
def test_evidence_records_reject_a_malformed_hash(field: str) -> None:
    record = next(s for s in SAMPLES if isinstance(s, EvidenceRecord))
    bad = [{"path": "evidence/x.json", "sha256": "xyz"}] if field == "files" else "xyz"
    with pytest.raises(ValidationError):
        EvidenceRecord.model_validate({**record.model_dump(), field: bad})
