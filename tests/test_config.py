from pathlib import Path
from typing import get_args

import pytest
import yaml
from pydantic import ValidationError

from cuas.config import (
    ScenarioMetadata,
    SensorSettings,
    SiteConfig,
    TargetType,
    ZoneLabels,
    load_site,
)


def raw_site(config_dir: Path) -> dict:
    return yaml.safe_load((config_dir / "site.yaml").read_text(encoding="utf-8"))


def test_site_holds_the_shared_baseline(site: SiteConfig) -> None:
    assert [s.id for s in site.stations] == ["st1", "st2", "st3"]
    assert len(site.pickets) == 8
    assert {z.id: z.weight for z in site.zones} == {
        "critical": 1.0,
        "important": 0.6,
        "perimeter": 0.3,
    }


def test_zoom_per_station_defaults_to_one(site: SiteConfig) -> None:
    assert site.zoom_per_station == 1


@pytest.mark.parametrize("value", [0, 1, 2])
def test_zoom_per_station_accepts_0_1_2(config_dir: Path, value: int) -> None:
    assert load_site(config_dir, zoom_per_station=value).zoom_per_station == value


@pytest.mark.parametrize("value", [3, -1, "2"])
def test_zoom_per_station_rejects_anything_else(
    config_dir: Path, value: object
) -> None:
    with pytest.raises(ValidationError):
        load_site(config_dir, zoom_per_station=value)  # type: ignore[arg-type]


def test_a_site_file_without_zoom_per_station_is_rejected(config_dir: Path) -> None:
    raw = raw_site(config_dir)
    del raw["zoom_per_station"]
    with pytest.raises(ValidationError):
        SiteConfig.model_validate(raw)


def test_unknown_settings_are_rejected(config_dir: Path) -> None:
    with pytest.raises(ValidationError):
        SiteConfig.model_validate({**raw_site(config_dir), "radar": True})


def test_sensor_values_match_the_design(site: SiteConfig) -> None:
    assert {k: s.sigma_deg for k, s in site.sensors.items()} == {
        "rgb": 0.05,
        "thermal": 0.1,
        "acoustic": 5.0,
    }
    assert site.sensors["acoustic"].base_range_m["bird"] == 0.0


def test_picket_values_match_the_design(site: SiteConfig) -> None:
    settings = site.picket_settings
    assert settings.engines["attack_drone"].hearing_radius_m == 1500.0
    assert settings.engines["quadcopter"].hearing_radius_m == 300.0
    assert settings.engines["attack_drone"].type == "piston"
    assert "bird" not in settings.engines
    assert settings.bearing_error_deg == 20.0
    assert settings.delay_s == (1.0, 2.0)


def test_every_sensor_needs_a_range_for_every_target_type(site: SiteConfig) -> None:
    good = site.sensors["rgb"].model_dump()
    assert set(good["base_range_m"]) == set(get_args(TargetType))
    del good["base_range_m"]["bird"]
    with pytest.raises(ValidationError):
        SensorSettings.model_validate(good)


def test_zone_labels_cover_exactly_the_site_zone_ids(site: SiteConfig) -> None:
    assert set(ZoneLabels.model_fields) == {zone.id for zone in site.zones}


def test_tracker_places_targets_with_cameras_only(site: SiteConfig) -> None:
    assert site.tracker.position_sensors == ("rgb", "thermal")
    assert site.tracker.min_ray_angle_deg == 15.0
    assert site.tracker.max_ray_miss_m == 30.0
    assert (site.gateway.max_future_s, site.gateway.max_age_s) == (2.0, 10.0)


@pytest.mark.parametrize(
    ("section", "changes"),
    [
        ("tracker", {"position_sensors": []}),
        ("tracker", {"position_sensors": ["radar"]}),
        ("tracker", {"min_ray_angle_deg": 0.0}),
        ("tracker", {"min_ray_angle_deg": 91.0}),
        ("tracker", {"confirm_fixes": 0}),
        ("tracker", {"merge_radius_m": -1.0}),
        ("gateway", {"max_age_s": 0.0}),
        ("gateway", {"max_future_s": -1.0}),
    ],
    ids=str,
)
def test_bad_tracker_and_gateway_values_fail_on_load(
    config_dir: Path, section: str, changes: dict[str, object]
) -> None:
    raw = raw_site(config_dir)
    raw[section] = {**raw[section], **changes}
    with pytest.raises(ValidationError):
        SiteConfig.model_validate(raw)


def test_decision_layer_values_match_the_design(site: SiteConfig) -> None:
    assert (site.classify.prior, site.classify.weights) == (
        0.1,
        {"look": 1.0, "move": 1.0, "sound": 1.0},
    )
    assert (site.threat.red, site.threat.amber, site.threat.zone_share) == (
        0.6,
        0.3,
        0.5,
    )
    assert site.threat.approved_flights == ()
    assert (site.coverage.zone, site.coverage.warning_below_pct) == ("important", 80.0)
    assert site.zoom.period_s == 0.6


@pytest.mark.parametrize(
    ("section", "changes"),
    [
        ("threat", {"amber": 0.7}),
        ("threat", {"urgency_full_s": 200.0}),
        ("classify", {"prior": 0.0}),
        ("classify", {"clue_floor": 0.5}),
        ("zoom", {"magnification": 0.5}),
        ("coverage", {"zone": "car park"}),
        ("coverage", {"warning_below_pct": 0.0}),
        ("alerts", {"relink_window_s": 0.0}),
    ],
    ids=str,
)
def test_bad_decision_layer_values_fail_on_load(
    config_dir: Path, section: str, changes: dict[str, object]
) -> None:
    raw = raw_site(config_dir)
    raw[section] = {**raw[section], **changes}
    with pytest.raises(ValidationError):
        SiteConfig.model_validate(raw)


def test_a_bad_movement_value_fails_on_load(config_dir: Path) -> None:
    raw = raw_site(config_dir)
    raw["classify"]["move"]["hover_fraction"] = 1.5
    with pytest.raises(ValidationError):
        SiteConfig.model_validate(raw)


def test_time_to_impact_fit_values_match_the_design(site: SiteConfig) -> None:
    move = site.classify.move
    assert (
        move.velocity_window_s,
        move.velocity_min_span_s,
        move.velocity_max_fix_age_s,
    ) == (5.0, 3.0, 6.5)


@pytest.mark.parametrize(
    "changes",
    [{"velocity_min_span_s": 6.0}, {"velocity_max_fix_age_s": 4.0}],
    ids=str,
)
def test_fit_spans_out_of_order_fail_on_load(
    config_dir: Path, changes: dict[str, float]
) -> None:
    raw = raw_site(config_dir)
    raw["classify"]["move"] = {**raw["classify"]["move"], **changes}
    with pytest.raises(ValidationError):
        SiteConfig.model_validate(raw)


def test_scenario_metadata_holds_no_truth() -> None:
    assert set(ScenarioMetadata.model_fields) == {"id", "title", "venue", "zone_labels"}
