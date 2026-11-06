"""Scenario files: the only place flight paths and target types are declared."""

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import Field

from cuas.config import (
    ConfigModel,
    NonNegative,
    Positive,
    ScenarioMetadata,
    SimulationSettings,
)
from cuas.schemas.base import Probability, Vector3

Seed = Annotated[int, Field(ge=0)]


class Waypoint(ConfigModel):
    position_enu_m: Vector3
    hover_s: NonNegative = 0.0


class LateralJitter(ConfigModel):
    amplitude_m: Positive
    period_s: Positive


class RouteTarget(ConfigModel):
    """A target that flies waypoints at constant speed. Its seed fixes its jitter."""

    id: str
    type: Literal["attack_drone", "quadcopter", "friendly_drone"]
    seed: Seed
    start_s: NonNegative
    speed_mps: Positive
    waypoints: tuple[Waypoint, ...] = Field(min_length=2)
    jitter: LateralJitter | None = None


class BirdFlock(ConfigModel):
    """``count`` birds wandering around a home point. Each bird becomes its own target."""

    id: str
    type: Literal["bird"]
    seed: Seed
    start_s: NonNegative
    count: Annotated[int, Field(ge=1)]
    home_enu_m: Vector3
    spread_m: Positive
    altitude_spread_m: NonNegative
    roam_radius_m: Positive
    speed_range_mps: tuple[Positive, Positive]
    turn_sigma_deg_per_sqrt_s: Positive
    turn_back_deg_per_s: Positive


TargetSpec = Annotated[RouteTarget | BirdFlock, Field(discriminator="type")]


class Environment(ConfigModel):
    visibility_factor: Probability
    wind_mps: NonNegative

    def wind_range_factor(self, settings: SimulationSettings) -> float:
        """Share of acoustic range left after wind (docs/design.md A10)."""
        return max(0.0, 1.0 - settings.wind_range_loss_per_mps * self.wind_mps)


class Scenario(ConfigModel):
    """Closed to unknown keys, so a scenario cannot override the site's geometry or zones."""

    metadata: ScenarioMetadata
    seed: Seed
    duration_s: Positive
    environment: Environment
    targets: tuple[TargetSpec, ...] = Field(min_length=1)


def available_scenarios(config_dir: Path) -> list[str]:
    return sorted(
        path.name.split("_")[0] for path in (config_dir / "scenarios").glob("*.yaml")
    )


def load_scenario(config_dir: Path, scenario_id: str) -> Scenario:
    matches = list((config_dir / "scenarios").glob(f"{scenario_id}_*.yaml"))
    if len(matches) != 1:
        raise FileNotFoundError(
            f"expected one file for scenario {scenario_id!r}, found {len(matches)}"
        )
    scenario = Scenario.model_validate(
        yaml.safe_load(matches[0].read_text(encoding="utf-8"))
    )
    if scenario.metadata.id != scenario_id:
        raise ValueError(f"{matches[0].name} declares id {scenario.metadata.id!r}")
    return scenario
