"""The dashboard contract, version 1: what the server sends on ``/ws`` and what its API takes.

This module is the one source of truth. ``docs/dashboard_contract.schema.json`` is generated from
it with ``scripts/record_stream.py --schema`` and a test keeps the two in step; the meaning of
each field is in ``docs/dashboard_contract.md``. Any change bumps ``CONTRACT_VERSION``.

Positions are local ENU metres (x east, y north, origin at the site centre). Angles are degrees,
azimuth 0 = north and clockwise. Times are simulated seconds. Nothing here depends on a map
background (docs/mapping.md).
"""

import json
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    TypeAdapter,
    model_serializer,
    model_validator,
)

CONTRACT_VERSION = 1
DECIMALS = 3  # every number sent: 1 mm, 0.001 degrees, 0.001 s, 0.001 probability
FRAME_DESCRIPTION = (
    "local ENU metres: x east, y north, origin at the site centre; north is up"
)

Level = Literal["red", "amber", "info"]
Compass = Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
Label = Literal["confirm", "dismiss"]
RecordKind = Literal["alert", "escalation", "label", "export", "camera_detection"]
XY = tuple[float, float]


def _rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, DECIMALS)
    if isinstance(value, list | tuple):
        return [_rounded(v) for v in value]
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    return value


class ContractModel(BaseModel):
    """Floats are rounded to ``DECIMALS`` places when sent: display precision, nothing more."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_serializer(mode="wrap")
    def _round_floats(self, handler: SerializerFunctionWrapHandler) -> Any:
        return _rounded(handler(self))


# --- site profiles and the site map ---------------------------------------------------------


class ScenarioChoice(ContractModel):
    scenario_id: str
    title: str


class SiteProfile(ContractModel):
    """A saved site the operator can pick: shared geometry plus one venue's labels."""

    profile_id: str
    venue: str
    zone_labels: dict[str, str]
    """Display label per zone ID, for example ``critical``."""
    scenarios: list[ScenarioChoice]
    """In the demo, monitoring replays one of these as the live sensor feed."""


class Bounds(ContractModel):
    min_x: float
    min_y: float
    max_x: float
    max_y: float


class ZoneView(ContractModel):
    zone_id: str
    label: str
    weight: float
    """0 to 1; the critical zone is 1.0."""
    polygon: list[XY]


class StationView(ContractModel):
    station_id: str
    x: float
    y: float
    z: float


class PicketView(ContractModel):
    picket_id: str
    x: float
    y: float


class SiteMap(ContractModel):
    frame: str = FRAME_DESCRIPTION
    bounds: Bounds
    """The area to fit on screen, margin included."""
    zones: list[ZoneView]
    """Outermost first, so drawing in order leaves the critical zone on top."""
    stations: list[StationView]
    pickets: list[PicketView]


# --- server to client, on /ws ----------------------------------------------------------------


class RunInfo(ContractModel):
    """Sent when a run starts, pauses, resumes, changes speed or ends."""

    contract: Literal[1] = CONTRACT_VERSION
    type: Literal["run"] = "run"
    run_id: str
    profile_id: str
    scenario_id: str
    title: str
    venue: str
    seed: int
    duration_s: float
    recorded_media: bool
    zoom_per_station: int
    state: Literal["running", "paused", "ended"]
    speed: float
    """Simulated seconds per wall second: 1, 2 or 5."""
    site: SiteMap
    ended_reason: Literal["completed", "stopped", "failed"] | None = None
    """Why an ended run ended: it played to the end, the operator stopped it, or it raised an
    error (the server console has it). ``None`` until it ends."""


class HeardView(ContractModel):
    """The latest microphone bearing the classifier matched to this track: a wedge from the
    station, as wide as a station microphone's ``pre_alert`` wedge. Never drawn from a station
    name, a clip or the map: only this link."""

    sensor_id: str
    """``station.acoustic``, for example ``st3.acoustic``."""
    station_id: str
    x: float
    y: float
    """The station."""
    bearing_deg: float
    compass: Compass
    half_width_deg: float
    t: float
    """When the station heard it."""


class TrackView(ContractModel):
    track_id: str
    status: Literal["tentative", "confirmed"]
    x: float
    y: float
    z: float
    vx: float
    vy: float
    n_stations: int
    """Stations in this fix. 0 means coasting on a prediction."""
    coasting: bool
    trail: list[tuple[float, float, float]]
    """``[t, x, y]`` over the last 20 s, oldest first."""
    level: Level | None
    alert_id: str | None
    p_drone: float | None
    p_attack_drone: float | None
    p_bird: float | None
    heard: list[HeardView] = []
    """Microphone bearings matched to this track. Empty in a simulator-only run."""


class LookRef(ContractModel):
    """A recording behind the look evidence, for the clip panel."""

    source: str
    """``station.sensor``, for example ``st1.rgb``, ``st1.thermal`` or ``st2.zoom``."""
    clip_url: str
    at_s: float
    """Seconds into the clip of the frame the model looked at (approximate)."""
    dataset: str | None = None
    """The public dataset the recording comes from, for its caption: never this track's
    footage. ``None`` if the server does not know."""


class SoundRef(ContractModel):
    """A station microphone's recording behind the sound clue, for the recorded-audio panel.

    The clean source: the classifier heard it mixed with background noise at a simulated
    distance and wind.
    """

    source: str
    """``station.acoustic``, for example ``st1.acoustic``."""
    station_id: str
    clip_url: str
    dataset: str | None = None
    """The public dataset the recording comes from, as for ``LookRef``."""


class AlertCard(ContractModel):
    """One alert, in the order the threat ranking published: level, time to impact, score.

    A card stays while its track is live, even if the level falls back to info.
    """

    alert_id: str
    track_id: str
    level: Level
    score: float
    tti_s: float | None
    zone_id: str | None
    zone_label: str | None
    approach: Literal["inside", "heading_to", "none"]
    class_key: Literal["attack", "drone", "unclassified"]
    confidence: float
    """P(attack drone) for ``attack``, otherwise P(drone)."""
    n_stations: int
    coasting: bool
    reasons: list[str]
    """Plain English from the threat ranking. Not yet translation keys."""
    label: Label | None
    evidence_records: int
    looks: list[LookRef]
    """Camera recordings. Empty in a simulator-only run: there are no recordings."""
    sounds: list[SoundRef] = []
    """Microphone recordings (WAV), clean sources. Empty in a simulator-only run."""


class PreAlert(ContractModel):
    """Heard but not placed: a picket's or a station microphone's wedge. Draw it and card it."""

    sector_id: str
    sensor_id: str
    x: float
    y: float
    """The wedge's origin: the picket or station."""
    bearing_deg: float
    compass: Compass
    half_width_deg: float
    first_t: float
    last_t: float
    reports: int


class PicketHeard(ContractModel):
    picket_id: str
    t: float


class Ray(ContractModel):
    """A bearing from the latest batch, for the bearing-ray overlay."""

    station_id: str
    sensor: str
    azimuth_deg: float
    elevation_deg: float
    sigma_deg: float


class ZoomView(ContractModel):
    station_id: str
    camera_id: str
    track_id: str
    azimuth_deg: float
    elevation_deg: float


class CoverageView(ContractModel):
    pct: float
    warning: bool
    reach_m: dict[str, float]
    """Each station's camera reach now, for greying uncovered areas."""


class SensorView(ContractModel):
    sensor_id: str
    ok: bool
    visibility: float


class EvidenceHead(ContractModel):
    seq: int
    record_hash: str


class SimCameraView(ContractModel):
    """What to draw in the SIMULATED camera view: no footage. The target direction is a camera's
    reported bearing, or the direction to the estimated track; never the true position."""

    camera: Literal["wide", "zoom"]
    station_id: str
    pointing_azimuth_deg: float
    pointing_elevation_deg: float
    fov_deg: float
    """Horizontal field of view."""
    seen_azimuth_deg: float
    seen_elevation_deg: float
    range_m: float | None
    """From the station to the estimated track; ``None`` before a track exists."""
    drawn_span_m: float
    """The size the target is drawn at, for its apparent size at ``range_m``."""


class CameraCue(ContractModel):
    """A big-drone engagement (piston engine heard by a picket), in three stages: ``acoustic``
    (camera cued, searching), ``camera`` (a camera reported a bearing near the cue), ``zoom``
    (a zoom camera is on its track). Small drones never get one."""

    cue_id: str
    picket_id: str
    heard_t: float
    stage: Literal["acoustic", "camera", "zoom"]
    cue_station_id: str
    cue_bearing_deg: float
    """From the cued station towards the picket that heard the engine."""
    detected_t: float | None
    detected_by: str | None
    track_id: str | None
    alert_id: str | None
    views: list[SimCameraView]
    current_rgb_t: float | None = None
    """Fresh RGB bearing uniquely linked by geometry to this track; never thermal."""
    """The wide view once detected, then the zoom view once a zoom camera is assigned."""


class Frame(ContractModel):
    """A snapshot, every 0.4 s of simulated time while a run is going."""

    contract: Literal[1] = CONTRACT_VERSION
    type: Literal["frame"] = "frame"
    run_id: str
    t: float
    tracks: list[TrackView]
    alerts: list[AlertCard]
    pre_alerts: list[PreAlert]
    pickets_heard: list[PicketHeard]
    """Picket alerts in the last few seconds: flash these pickets."""
    rays: list[Ray]
    zoom: list[ZoomView]
    coverage: CoverageView | None
    sensors: list[SensorView]
    evidence_head: EvidenceHead | None
    cues: list[CameraCue] = []
    """Big-drone camera cues (S1, S5); always empty for small drones."""


class ModelStep(ContractModel):
    """One step of loading the AI models: a model, or the warm-up inference."""

    name: str
    state: Literal["waiting", "loading", "ready", "missing", "failed"]
    detail: str | None = None
    """Why a step is missing or failed, in words."""


class ModelStatus(ContractModel):
    """Sent as the server loads the AI models at start, once per step. ``ready``: recorded-media
    runs can start. ``failed``: they cannot, and the steps say which model and why; simulator
    runs are unaffected."""

    contract: Literal[1] = CONTRACT_VERSION
    type: Literal["models"] = "models"
    state: Literal["loading", "ready", "failed"]
    steps: list[ModelStep]


class Hello(ContractModel):
    """The first message on every connection."""

    contract: Literal[1] = CONTRACT_VERSION
    type: Literal["hello"] = "hello"
    profiles: list[SiteProfile]
    run: RunInfo | None
    frame: Frame | None
    models: ModelStatus | None = None
    """``None``: this server loads no models, as a replay does."""


class EvidenceEvent(ContractModel):
    contract: Literal[1] = CONTRACT_VERSION
    type: Literal["evidence"] = "evidence"
    run_id: str
    seq: int
    kind: RecordKind
    alert_id: str
    t: float
    record_hash: str


ServerMessage = Annotated[
    Hello | RunInfo | Frame | EvidenceEvent | ModelStatus, Field(discriminator="type")
]


# --- client to server, over HTTP JSON -------------------------------------------------------


class StartRun(ContractModel):
    profile_id: str
    scenario_id: str
    seed: int | None = None
    recorded_media: bool = False
    zoom_per_station: Literal[0, 1, 2] | None = None


class RunControl(ContractModel):
    action: Literal["pause", "play", "speed"]
    speed: Literal[1, 2, 5] | None = None

    @model_validator(mode="after")
    def _speed_with_speed(self) -> "RunControl":
        if (self.action == "speed") != (self.speed is not None):
            raise ValueError("give speed with action 'speed', and only then")
        return self


class LabelRequest(ContractModel):
    label: Label


class LabelResult(ContractModel):
    alert_id: str
    seq: int
    record_hash: str


class ExportResult(ContractModel):
    alert_id: str
    path: str
    sha256: str
    package: dict[str, Any]
    """A hand-off package, as in docs/handoff.schema.json."""


class ApiError(ContractModel):
    detail: str


HTTP_MODELS: tuple[type[ContractModel], ...] = (
    StartRun,
    RunControl,
    LabelRequest,
    LabelResult,
    ExportResult,
    ApiError,
    SiteProfile,
)


def contract_schema() -> dict[str, Any]:
    """The JSON Schema of every server message and every HTTP body."""
    return {
        "title": "C-UAS dashboard contract",
        "contract": CONTRACT_VERSION,
        "server_messages": TypeAdapter(ServerMessage).json_schema(),
        "http": {model.__name__: model.model_json_schema() for model in HTTP_MODELS},
    }


def schema_text() -> str:
    return json.dumps(contract_schema(), indent=1, sort_keys=True) + "\n"
