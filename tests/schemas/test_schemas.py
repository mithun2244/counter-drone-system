import re
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from cuas import schemas
from cuas.schemas import (
    BearingDetection,
    ClueEvidence,
    EvidenceRecord,
    Message,
    PicketAlert,
    RejectedMessage,
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
        p_drone=0.9,
        p_bird=0.1,
        p_attack_drone=0.8,
        evidence=ClueEvidence(look=0.9, move=0.8),
    ),
    ThreatAssessment(
        track_id="trk1",
        score=0.7,
        level="red",
        zone="critical",
        time_to_impact_s=24.0,
        reasons=("fast straight flight",),
    ),
    ZoomTask(
        station_id="st1",
        camera_id="z1",
        track_id="trk1",
        azimuth_deg=10.0,
        elevation_deg=2.0,
    ),
    EvidenceRecord(
        alert_id="a1", track_id="trk1", clip_path="c.mp4", sha256=HASH, prev_hash=None
    ),
    RejectedMessage(reason="unknown sensor", raw="{}"),
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
    assert len(messages) == 9
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
        len(models_in_schemas()) == 11
    )  # 9 messages, ClueEvidence and the Message base
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


def test_evidence_record_rejects_a_malformed_hash() -> None:
    with pytest.raises(ValidationError):
        EvidenceRecord(
            alert_id="a", track_id="t", clip_path="c", sha256="xyz", prev_hash=None
        )
