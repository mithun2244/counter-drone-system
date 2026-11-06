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


class SiteConfig(ConfigModel):
    """The baseline every scenario shares."""

    zoom_per_station: Literal[0, 1, 2]
    simulation: SimulationSettings
    stations: tuple[Placement, ...]
    pickets: tuple[Placement, ...]
    zones: tuple[Zone, ...]
    sensors: dict[SensorKind, SensorSettings]
    picket_settings: PicketSettings


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
