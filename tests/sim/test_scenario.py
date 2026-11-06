import math
import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from cuas.config import SiteConfig
from cuas.sim.scenario import (
    BirdFlock,
    RouteTarget,
    Scenario,
    available_scenarios,
    load_scenario,
)

ALL_IDS = ["s1", "s2", "s3", "s4"]
INDUSTRIAL = {
    "critical": "Processing Unit",
    "important": "Plant Area",
    "perimeter": "Site Perimeter",
}
STADIUM = {
    "critical": "Pitch and Stands",
    "important": "Stadium Grounds",
    "perimeter": "Event Perimeter",
}
MAX_SCENARIO_S = 300.0  # prd.md section 7: each scenario runs in under 5 minutes


def routes(scenario: Scenario) -> list[RouteTarget]:
    return [t for t in scenario.targets if isinstance(t, RouteTarget)]


def flocks(scenario: Scenario) -> list[BirdFlock]:
    return [t for t in scenario.targets if isinstance(t, BirdFlock)]


def test_the_four_scenarios_are_available(config_dir: Path) -> None:
    assert available_scenarios(config_dir) == ALL_IDS


@pytest.mark.parametrize("scenario_id", ALL_IDS)
def test_scenario_is_valid_fictional_and_short_enough(
    config_dir: Path, scenario_id: str
) -> None:
    scenario = load_scenario(config_dir, scenario_id)
    assert scenario.metadata.id == scenario_id
    assert scenario.metadata.venue.startswith("Fictional")
    assert scenario.duration_s < MAX_SCENARIO_S


def test_s1_has_exactly_three_attack_drones_within_design_ranges(
    config_dir: Path,
) -> None:
    targets = load_scenario(config_dir, "s1").targets
    assert [t.type for t in targets] == ["attack_drone"] * 3
    for target in targets:
        assert target.speed_mps == 50.0
        for waypoint in target.waypoints:
            assert 50.0 <= waypoint.position_enu_m[2] <= 150.0


def test_s1_drones_start_beyond_picket_hearing_and_end_at_the_site_centre(
    config_dir: Path, site: SiteConfig
) -> None:
    ring_radius = max(math.hypot(*p.position_enu_m[:2]) for p in site.pickets)
    hearing = site.picket_settings.engines["attack_drone"].hearing_radius_m
    for target in load_scenario(config_dir, "s1").targets:
        assert (
            math.hypot(*target.waypoints[0].position_enu_m[:2]) > ring_radius + hearing
        )
        assert target.waypoints[-1].position_enu_m[:2] == (0.0, 0.0)


def test_s2_has_exactly_one_quadcopter_within_design_ranges(config_dir: Path) -> None:
    targets = load_scenario(config_dir, "s2").targets
    assert [t.type for t in targets] == ["quadcopter"]
    assert 5.0 <= targets[0].speed_mps <= 15.0
    assert any(w.hover_s > 0 for w in targets[0].waypoints)


def test_s3_has_a_flock_and_one_quadcopter_within_design_ranges(
    config_dir: Path,
) -> None:
    scenario = load_scenario(config_dir, "s3")
    assert [t.type for t in routes(scenario)] == ["quadcopter"]
    assert 5.0 <= routes(scenario)[0].speed_mps <= 15.0
    flock = flocks(scenario)[0]
    assert flock.count > 1
    assert 5.0 <= flock.speed_range_mps[0] <= flock.speed_range_mps[1] <= 20.0


def test_s4_is_s2_in_a_dust_storm(config_dir: Path) -> None:
    s2, s4 = load_scenario(config_dir, "s2"), load_scenario(config_dir, "s4")
    assert s4.targets == s2.targets
    assert s4.seed == s2.seed
    assert s4.duration_s == s2.duration_s
    assert s4.environment.visibility_factor < s2.environment.visibility_factor
    assert s4.environment.wind_mps > s2.environment.wind_mps


@pytest.mark.parametrize(
    ("scenario_id", "labels"),
    [("s1", INDUSTRIAL), ("s2", STADIUM), ("s3", STADIUM), ("s4", STADIUM)],
)
def test_zone_labels(
    config_dir: Path, scenario_id: str, labels: dict[str, str]
) -> None:
    metadata = load_scenario(config_dir, scenario_id).metadata
    assert metadata.zone_labels.model_dump() == labels


def scenario_file(config_dir: Path, scenario_id: str) -> Path:
    return next((config_dir / "scenarios").glob(f"{scenario_id}_*.yaml"))


@pytest.mark.parametrize("scenario_id", ["s2", "s3", "s4"])
def test_stadium_scenarios_never_mention_industrial_labels(
    config_dir: Path, scenario_id: str
) -> None:
    text = scenario_file(config_dir, scenario_id).read_text(encoding="utf-8")
    for label in INDUSTRIAL.values():
        assert label not in text


@pytest.mark.parametrize("scenario_id", ALL_IDS)
def test_metadata_does_not_give_away_the_targets(
    config_dir: Path, scenario_id: str
) -> None:
    """Metadata goes to components that must not see truth, so it cannot describe the targets."""
    metadata = load_scenario(config_dir, scenario_id).metadata
    assert not re.search(
        "drone|quad|bird|flock|attack|wave", metadata.model_dump_json(), re.IGNORECASE
    )


@pytest.mark.parametrize("key", ["stations", "pickets", "zones"])
def test_a_scenario_cannot_override_the_site(config_dir: Path, key: str) -> None:
    raw = yaml.safe_load(scenario_file(config_dir, "s2").read_text(encoding="utf-8"))
    raw[key] = []
    with pytest.raises(ValidationError):
        Scenario.model_validate(raw)


def test_every_zone_needs_a_label(config_dir: Path) -> None:
    raw = yaml.safe_load(scenario_file(config_dir, "s2").read_text(encoding="utf-8"))
    del raw["metadata"]["zone_labels"]["critical"]
    with pytest.raises(ValidationError):
        Scenario.model_validate(raw)


def test_an_unknown_scenario_fails_loudly(config_dir: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_scenario(config_dir, "s9")


def test_a_file_declaring_the_wrong_id_fails_loudly(
    config_dir: Path, tmp_path: Path
) -> None:
    (tmp_path / "scenarios").mkdir()
    text = scenario_file(config_dir, "s2").read_text(encoding="utf-8")
    (tmp_path / "scenarios" / "s7_copy.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="declares id"):
        load_scenario(tmp_path, "s7")
