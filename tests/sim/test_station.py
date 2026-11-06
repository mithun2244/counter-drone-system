import math

import numpy as np
import pytest

from cuas.config import SensorSettings, SiteConfig
from cuas.geometry import angle_difference_deg
from cuas.schemas import BearingDetection
from cuas.sim.scenario import Environment
from cuas.sim.station import StationSim, detection_probability, in_field_of_view

CLEAR = Environment(visibility_factor=1.0, wind_mps=0.0)
ELEVATION_DEG = 10.0  # above the camera horizon mask
TICKS = 10_000


def sim(
    site: SiteConfig, environment: Environment = CLEAR, seed: int = 1
) -> StationSim:
    return StationSim(site.stations[0], site, environment, seed)


def position_at(
    site: SiteConfig,
    range_m: float,
    azimuth_deg: float = 90.0,
    elevation_deg: float = ELEVATION_DEG,
) -> tuple[float, float, float]:
    """A point at a known range and bearing from the first station."""
    x, y, z = site.stations[0].position_enu_m
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    return (
        x + range_m * math.sin(az) * math.cos(el),
        y + range_m * math.cos(az) * math.cos(el),
        z + range_m * math.sin(el),
    )


def bearings(
    station: StationSim,
    position: tuple[float, float, float],
    target_type: str = "quadcopter",
    ticks: int = TICKS,
) -> list[BearingDetection]:
    return [
        bearing
        for tick in range(ticks)
        for bearing, _ in station.observe("t", target_type, position, tick * 0.2)  # type: ignore[arg-type]
    ]


@pytest.mark.parametrize(
    ("range_m", "max_range_m", "p0", "expected"),
    [
        (0.0, 800.0, 0.95, 0.95),
        (400.0, 800.0, 0.95, 0.75 * 0.95),
        (800.0, 800.0, 0.95, 0.0),
        (801.0, 800.0, 0.95, 0.0),
        (0.0, 0.0, 0.95, 0.0),  # birds are inaudible: their acoustic range is zero
    ],
)
def test_detection_probability_known_answers(
    range_m: float, max_range_m: float, p0: float, expected: float
) -> None:
    assert detection_probability(range_m, max_range_m, p0) == pytest.approx(expected)


@pytest.mark.parametrize("sensor", ["rgb", "thermal", "acoustic"])
def test_nothing_is_detected_outside_the_range(site: SiteConfig, sensor: str) -> None:
    max_range_m = site.sensors[sensor].base_range_m["quadcopter"]
    found = bearings(sim(site), position_at(site, 1.01 * max_range_m))
    assert [b for b in found if b.sensor == sensor] == []


@pytest.mark.parametrize("sensor", ["rgb", "thermal", "acoustic"])
def test_detection_rate_matches_the_formula_at_half_range(
    site: SiteConfig, sensor: str
) -> None:
    settings = site.sensors[sensor]
    max_range_m = settings.base_range_m["quadcopter"]
    found = bearings(sim(site), position_at(site, max_range_m / 2))
    rate = sum(b.sensor == sensor for b in found) / TICKS
    assert rate == pytest.approx(0.75 * settings.p0, abs=0.02)


@pytest.mark.parametrize("sensor", ["rgb", "thermal", "acoustic"])
def test_bearing_noise_matches_the_configured_sigma(
    site: SiteConfig, sensor: str
) -> None:
    sigma = site.sensors[sensor].sigma_deg
    found = [
        b for b in bearings(sim(site), position_at(site, 50.0)) if b.sensor == sensor
    ]
    assert all(b.sigma_deg == sigma for b in found)
    azimuth_errors = np.array(
        [angle_difference_deg(b.azimuth_deg, 90.0) for b in found]
    )
    elevation_errors = np.array([b.elevation_deg - ELEVATION_DEG for b in found])
    for errors in (azimuth_errors, elevation_errors):
        assert errors.std() == pytest.approx(sigma, rel=0.05)
        assert abs(errors.mean()) < 4 * sigma / math.sqrt(len(found))


def narrow(site: SiteConfig, **changes: float) -> SensorSettings:
    return site.sensors["rgb"].model_copy(update=changes)


@pytest.mark.parametrize(
    ("azimuth", "visible"), [(44.0, True), (46.0, False), (316.0, True), (314.0, False)]
)
def test_field_of_view_limits_azimuth(
    site: SiteConfig, azimuth: float, visible: bool
) -> None:
    settings = narrow(site, boresight_az_deg=0.0, hfov_deg=90.0)
    assert in_field_of_view(azimuth, ELEVATION_DEG, settings) is visible


def test_field_of_view_wraps_past_north(site: SiteConfig) -> None:
    settings = narrow(site, boresight_az_deg=350.0, hfov_deg=40.0)
    assert in_field_of_view(5.0, ELEVATION_DEG, settings)
    assert not in_field_of_view(15.0, ELEVATION_DEG, settings)


@pytest.mark.parametrize(
    ("elevation", "visible"), [(0.4, False), (0.5, True), (85.0, True), (85.1, False)]
)
def test_elevation_limits_apply(
    site: SiteConfig, elevation: float, visible: bool
) -> None:
    assert in_field_of_view(90.0, elevation, site.sensors["rgb"]) is visible


def test_a_target_below_the_horizon_mask_is_not_seen_by_cameras(
    site: SiteConfig,
) -> None:
    found = bearings(sim(site), position_at(site, 50.0, elevation_deg=0.1), ticks=500)
    assert {b.sensor for b in found} == {"acoustic"}


def test_a_narrow_view_stops_detections_outside_it(site: SiteConfig) -> None:
    sensors = dict(site.sensors)
    sensors["rgb"] = narrow(site, boresight_az_deg=0.0, hfov_deg=90.0)
    narrowed = site.model_copy(update={"sensors": sensors})
    behind = bearings(
        sim(narrowed), position_at(site, 50.0, azimuth_deg=180.0), ticks=500
    )
    ahead = bearings(sim(narrowed), position_at(site, 50.0, azimuth_deg=0.1), ticks=500)
    assert "rgb" not in {b.sensor for b in behind}
    assert "rgb" in {b.sensor for b in ahead}


def test_visibility_cuts_camera_range_but_not_acoustic(site: SiteConfig) -> None:
    dusty = Environment(visibility_factor=0.5, wind_mps=0.0)
    # At 0.6 of the camera range: inside it in clear air, outside it at half visibility.
    position = position_at(site, 0.6 * site.sensors["rgb"].base_range_m["attack_drone"])
    clear_sensors = {
        b.sensor for b in bearings(sim(site), position, "attack_drone", 500)
    }
    dusty_sensors = {
        b.sensor for b in bearings(sim(site, dusty), position, "attack_drone", 500)
    }
    assert "rgb" in clear_sensors
    assert "rgb" not in dusty_sensors

    near = position_at(site, 100.0)
    assert "acoustic" in {b.sensor for b in bearings(sim(site, dusty), near, ticks=500)}


def test_wind_cuts_acoustic_range_but_not_camera(site: SiteConfig) -> None:
    windy = Environment(
        visibility_factor=1.0, wind_mps=25.0
    )  # half range at 2% per m/s
    position = position_at(
        site, 0.6 * site.sensors["acoustic"].base_range_m["quadcopter"]
    )
    assert "acoustic" in {b.sensor for b in bearings(sim(site), position, ticks=500)}
    windy_sensors = {b.sensor for b in bearings(sim(site, windy), position, ticks=500)}
    assert "acoustic" not in windy_sensors
    assert "rgb" in windy_sensors


def test_birds_are_seen_but_never_heard(site: SiteConfig) -> None:
    found = bearings(sim(site), position_at(site, 50.0), "bird", 500)
    assert {b.sensor for b in found} == {"rgb", "thermal"}


def test_azimuth_stays_in_range_near_north(site: SiteConfig) -> None:
    found = bearings(sim(site), position_at(site, 20.0, azimuth_deg=0.0))
    azimuths = [b.azimuth_deg for b in found if b.sensor == "acoustic"]
    assert all(0.0 <= azimuth < 360.0 for azimuth in azimuths)
    assert max(azimuths) > 350.0  # noise really did cross north


def test_elevation_stays_in_range_near_vertical(site: SiteConfig) -> None:
    found = bearings(sim(site), position_at(site, 20.0, elevation_deg=89.9))
    elevations = [b.elevation_deg for b in found if b.sensor == "acoustic"]
    assert max(elevations) == 90.0


def test_noise_is_aligned_when_only_the_range_changes(site: SiteConfig) -> None:
    dusty = Environment(visibility_factor=0.5, wind_mps=0.0)
    position = position_at(site, 300.0)
    clear = bearings(sim(site), position, ticks=500)
    reduced = bearings(sim(site, dusty), position, ticks=500)
    assert 0 < len(reduced) < len(clear)
    assert set(map(str, reduced)) <= set(map(str, clear))


def test_bearings_carry_no_model_output_until_phase_2(site: SiteConfig) -> None:
    for bearing in bearings(sim(site), position_at(site, 50.0), ticks=50):
        assert bearing.class_probs == {}
        assert bearing.snapshot_ref is None


def test_truth_records_the_real_geometry(site: SiteConfig) -> None:
    station = sim(site)
    observations = station.observe("quad-1", "quadcopter", position_at(site, 50.0), 2.0)
    assert observations
    for bearing, truth in observations:
        assert truth.target_id == "quad-1"
        assert truth.target_type == "quadcopter"
        assert truth.station_id == bearing.station_id == "st1"
        assert truth.sensor == bearing.sensor
        assert truth.t == bearing.t == 2.0
        assert truth.azimuth_deg == pytest.approx(90.0)
        assert truth.elevation_deg == pytest.approx(ELEVATION_DEG)
        assert truth.range_m == pytest.approx(50.0)
        assert (
            truth.max_range_m == site.sensors[truth.sensor].base_range_m["quadcopter"]
        )


def test_status_reports_each_sensors_range_factor(site: SiteConfig) -> None:
    environment = Environment(visibility_factor=0.5, wind_mps=10.0)
    statuses = {s.sensor_id: s for s in sim(site, environment).statuses(3.0)}
    assert statuses["st1.rgb"].visibility_factor == 0.5
    assert statuses["st1.thermal"].visibility_factor == 0.5
    assert statuses["st1.acoustic"].visibility_factor == pytest.approx(0.8)
    assert all(s.ok and s.t == 3.0 for s in statuses.values())
