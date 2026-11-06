import math

import pytest

from cuas.config import SiteConfig
from cuas.geometry import angle_difference_deg
from cuas.sim.picket import PicketSim, Report, guess_engine
from cuas.sim.rng import stream

TICK = 0.2
TICKS = 2000


def sim(site: SiteConfig, wind_factor: float = 1.0, seed: int = 1) -> PicketSim:
    return PicketSim(site.pickets[0], site.picket_settings, TICK, wind_factor, seed)


def position_at(
    site: SiteConfig, distance_m: float, azimuth_deg: float = 90.0
) -> tuple[float, float, float]:
    x, y, z = site.pickets[0].position_enu_m
    az = math.radians(azimuth_deg)
    return x + distance_m * math.sin(az), y + distance_m * math.cos(az), z


def run(
    picket: PicketSim,
    position: tuple[float, float, float],
    target_type: str = "attack_drone",
    ticks: int = TICKS,
) -> list[Report]:
    reports: list[Report] = []
    for tick in range(ticks):
        t = tick * TICK
        picket.listen("t", target_type, position, tick, t)  # type: ignore[arg-type]
        reports.extend(picket.due(tick, t))
    return reports


@pytest.mark.parametrize(
    ("target_type", "radius_m"),
    [("attack_drone", 1500.0), ("quadcopter", 300.0), ("friendly_drone", 300.0)],
)
def test_hearing_radius_by_target_type(
    site: SiteConfig, target_type: str, radius_m: float
) -> None:
    assert run(sim(site), position_at(site, 0.99 * radius_m), target_type, 100)
    assert not run(sim(site), position_at(site, 1.01 * radius_m), target_type, 100)


def test_birds_never_trigger_a_picket(site: SiteConfig) -> None:
    assert not run(sim(site), position_at(site, 1.0), "bird")


def test_wind_shrinks_the_hearing_radius(site: SiteConfig) -> None:
    position = position_at(site, 1400.0)
    assert run(sim(site), position, ticks=100)
    assert not run(sim(site, wind_factor=0.76), position, ticks=100)


def test_delay_is_one_to_two_seconds(site: SiteConfig) -> None:
    reports = run(sim(site), position_at(site, 500.0))
    delays = [truth.t - truth.heard_t for _, truth in reports]
    assert min(delays) >= 1.0 - 1e-9
    assert max(delays) <= 2.0 + 1e-9
    assert max(delays) > min(delays)  # the delay really varies


def test_nothing_is_reported_before_its_delay_has_passed(site: SiteConfig) -> None:
    picket = sim(site)
    picket.listen("t", "attack_drone", position_at(site, 500.0), 0, 0.0)
    assert picket.due(0, 0.0) == []
    assert picket.due(4, 4 * TICK) == []  # 0.8 s is under the shortest delay
    assert len(picket.due(10, 10 * TICK)) == 1  # 2 s is the longest delay


def test_bearing_error_is_within_twenty_degrees_and_really_varies(
    site: SiteConfig,
) -> None:
    reports = run(sim(site), position_at(site, 500.0))
    errors = [
        angle_difference_deg(alert.bearing_deg, truth.bearing_deg)
        for alert, truth in reports
    ]
    assert max(abs(error) for error in errors) <= 20.0
    assert max(errors) > 10.0
    assert min(errors) < -10.0


def test_reports_repeat_at_the_report_period_while_heard(site: SiteConfig) -> None:
    reports = run(sim(site), position_at(site, 500.0), ticks=100)  # 20 s
    heard = [truth.heard_t for _, truth in reports]
    period = site.picket_settings.report_period_s
    assert heard == pytest.approx([n * 10 * TICK for n in range(len(heard))])
    assert heard[1] - heard[0] == pytest.approx(period)


def test_each_target_is_reported_separately(site: SiteConfig) -> None:
    picket = sim(site)
    position = position_at(site, 500.0)
    picket.listen("a", "attack_drone", position, 0, 0.0)
    picket.listen("b", "attack_drone", position, 0, 0.0)
    assert {truth.target_id for _, truth in picket.due(20, 4.0)} == {"a", "b"}


def test_loudness_falls_with_distance(site: SiteConfig) -> None:
    def mean_loudness(distance_m: float) -> float:
        reports = run(sim(site), position_at(site, distance_m))
        return sum(alert.loudness for alert, _ in reports) / len(reports)

    assert mean_loudness(100.0) > mean_loudness(1400.0) + 0.5


def test_engine_guess_is_right_about_as_often_as_configured_but_not_always(
    site: SiteConfig,
) -> None:
    reports = run(sim(site), position_at(site, 500.0), ticks=20_000)
    right = sum(t.guessed_engine_type == t.engine_type for _, t in reports)
    accuracy = site.picket_settings.engine_guess_accuracy
    assert right / len(reports) == pytest.approx(accuracy, abs=0.05)
    assert right < len(reports)


def test_engine_probabilities_sum_to_one_and_favour_the_guess(site: SiteConfig) -> None:
    for alert, truth in run(sim(site), position_at(site, 500.0)):
        probs = alert.engine_type_probs
        assert sum(probs.values()) == pytest.approx(1.0)
        assert max(probs, key=probs.get) == truth.guessed_engine_type


def test_engine_guess_with_a_single_engine_type_is_certain() -> None:
    assert guess_engine("piston", ["piston"], 0.8, stream(1, "t")) == (
        "piston",
        {"piston": 1.0},
    )


def test_status_reports_the_wind_factor(site: SiteConfig) -> None:
    status = sim(site, wind_factor=0.76).status(4.0)
    assert status.sensor_id == "pk1"
    assert status.visibility_factor == 0.76
    assert status.ok
    assert status.t == 4.0
