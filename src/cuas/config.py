"""Typed site configuration and truth-free scenario metadata."""

from pathlib import Path
from typing import Annotated, Literal, Self, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from cuas.schemas import SensorKind
from cuas.schemas.base import Probability, Vector3

TargetType = Literal["attack_drone", "quadcopter", "friendly_drone", "bird"]
ZoneId = Literal["critical", "important", "perimeter"]
Positive = Annotated[float, Field(gt=0.0)]
NonNegative = Annotated[float, Field(ge=0.0)]


class ConfigModel(BaseModel):
    """Frozen and closed, so a misspelt or misplaced setting fails loudly when loaded."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SimulationSettings(ConfigModel):
    tick_s: Positive
    status_period_s: Positive
    wind_range_loss_per_mps: NonNegative


class Placement(ConfigModel):
    id: str
    position_enu_m: Vector3


class Zone(ConfigModel):
    id: ZoneId
    weight: Probability
    polygon_enu_m: tuple[tuple[float, float], ...]


class SensorSettings(ConfigModel):
    p0: Probability
    sigma_deg: Positive
    boresight_az_deg: Annotated[float, Field(ge=0.0, lt=360.0)]
    hfov_deg: Annotated[float, Field(gt=0.0, le=360.0)]
    min_elevation_deg: Annotated[float, Field(ge=-90.0, le=90.0)]
    max_elevation_deg: Annotated[float, Field(ge=-90.0, le=90.0)]
    base_range_m: dict[TargetType, NonNegative]

    @model_validator(mode="after")
    def _covers_every_target_type(self) -> Self:
        missing = set(get_args(TargetType)) - set(self.base_range_m)
        if missing:
            raise ValueError(f"base_range_m has no value for {sorted(missing)}")
        return self


class EngineSettings(ConfigModel):
    type: str
    hearing_radius_m: Positive


class PicketSettings(ConfigModel):
    engines: dict[TargetType, EngineSettings]
    bearing_error_deg: NonNegative
    delay_s: tuple[NonNegative, NonNegative]
    report_period_s: Positive
    engine_guess_accuracy: Probability
    loudness_sigma: NonNegative


class SplitSettings(ConfigModel):
    fractions: dict[str, Probability]
    salt: str
    min_test_clips: Annotated[int, Field(ge=1)]
    audio_block_clips: Annotated[int, Field(ge=1)]
    scene_max_hamming: Annotated[int, Field(ge=0)]


class DetectorSettings(ConfigModel):
    classes: tuple[str, ...]
    input_size: Annotated[int, Field(gt=0)]
    anchor_scales: tuple[Positive, ...]
    min_score: Probability
    max_candidates: Annotated[int, Field(ge=1)]
    max_detections: Annotated[int, Field(ge=1)]
    threads: Annotated[int, Field(ge=1)]


class LookSettings(ConfigModel):
    m: Annotated[int, Field(ge=1)]
    n: Annotated[int, Field(ge=1)]
    max_step_fraction: Positive
    """How far a target may move between looks, as a share of the frame width."""
    max_missed: Annotated[int, Field(ge=0)]
    period_s: Positive
    range_bins_m: dict[str, tuple[Positive, Positive]]
    """Where each label's Close and Medium distance bins end, from the dataset's article."""


class TrainingSettings(ConfigModel):
    seed: Annotated[int, Field(ge=0)]
    batch_size: Annotated[int, Field(ge=1)]
    learning_rate: Positive
    weight_decay: NonNegative
    epochs: Annotated[int, Field(ge=1)]
    max_minutes: Positive
    freeze_backbone: bool
    train_frames_per_clip: Annotated[int, Field(ge=1)]
    val_frames_per_clip: Annotated[int, Field(ge=1)]


class SoundTrainingSettings(ConfigModel):
    seed: Annotated[int, Field(ge=0)]
    batch_size: Annotated[int, Field(ge=1)]
    learning_rate: Positive
    weight_decay: NonNegative
    epochs: Annotated[int, Field(ge=1)]
    windows_per_clip: Annotated[int, Field(ge=1)]
    clean_fraction: Probability
    snr_range_db: tuple[float, float]


class MixingSettings(ConfigModel):
    reference_range_m: Positive
    reference_snr_db: float
    wind_loss_db_per_mps: NonNegative
    min_snr_db: float
    max_snr_db: float


class SoundSettings(ConfigModel):
    classes: tuple[str, ...]
    sample_rate: Annotated[int, Field(gt=0)]
    window_s: Positive
    n_fft: Annotated[int, Field(gt=0)]
    hop: Annotated[int, Field(gt=0)]
    n_mels: Annotated[int, Field(gt=0)]
    evaluation_snr_db: tuple[float, ...]
    mixing: MixingSettings
    training: SoundTrainingSettings

    @property
    def window_samples(self) -> int:
        return round(self.window_s * self.sample_rate)


class EvaluationSettings(ConfigModel):
    iou_hit: Probability
    iou_strict: Probability


class StationAiSettings(ConfigModel):
    split: SplitSettings
    detector: DetectorSettings
    look: LookSettings
    training: TrainingSettings
    evaluation: EvaluationSettings
    sound: SoundSettings


class SiteConfig(ConfigModel):
    """The baseline every scenario shares."""

    zoom_per_station: Literal[0, 1, 2]
    simulation: SimulationSettings
    stations: tuple[Placement, ...]
    pickets: tuple[Placement, ...]
    zones: tuple[Zone, ...]
    sensors: dict[SensorKind, SensorSettings]
    picket_settings: PicketSettings
    station_ai: StationAiSettings


class ZoneLabels(ConfigModel):
    """One display label per zone ID. Zone IDs and weights stay in ``site.yaml``."""

    critical: str
    important: str
    perimeter: str


class ScenarioMetadata(ConfigModel):
    """The part of a scenario any component may see. It holds no targets or flight paths."""

    id: str
    title: str
    venue: str
    zone_labels: ZoneLabels


def load_site(config_dir: Path, zoom_per_station: int | None = None) -> SiteConfig:
    raw = yaml.safe_load((config_dir / "site.yaml").read_text(encoding="utf-8"))
    if zoom_per_station is not None:
        raw["zoom_per_station"] = zoom_per_station
    return SiteConfig.model_validate(raw)
