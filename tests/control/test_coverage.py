"""Coverage on hand-checkable grids, and the site's clear and dusty figures."""

import pytest

from cuas.config import CoverageSettings, SiteConfig, Zone
from cuas.control.coverage import CoverageMonitor, grid
from cuas.schemas import SensorStatus

SQUARE_100 = ((-50.0, -50.0), (50.0, -50.0), (50.0, 50.0), (-50.0, 50.0))


def test_the_grid_has_one_centre_per_cell() -> None:
    centres = grid(SQUARE_100, 50.0)
    assert sorted(map(tuple, centres.tolist())) == [
        (-25.0, -25.0),
        (-25.0, 25.0),
        (25.0, -25.0),
        (25.0, 25.0),
    ]


def small(min_stations: int, warning: float = 80.0) -> CoverageMonitor:
    settings = CoverageSettings(
        zone="critical",
        cell_m=50.0,
        design_target="quadcopter",
        sensor="rgb",
        min_stations=min_stations,
        warning_below_pct=warning,
    )
    zone = Zone(id="critical", weight=1.0, polygon_enu_m=SQUARE_100)
    stations = {"a": (-25.0, -25.0, 15.0), "b": (25.0, -25.0, 15.0)}
    return CoverageMonitor(settings, [zone], stations, 30.0)


def test_cells_count_when_enough_stations_reach_them() -> None:
    """Reach 30 m: each station reaches its own cell only; the two top cells are 50 m away."""
    assert small(1).percent() == pytest.approx(50.0)
    assert small(2).percent() == pytest.approx(0.0)


def status(sensor_id: str, factor: float, t: float = 1.0) -> SensorStatus:
    return SensorStatus(sensor_id=sensor_id, ok=True, visibility_factor=factor, t=t)


def test_reported_visibility_shrinks_the_reach() -> None:
    monitor = small(1)
    monitor.report(
        status("a.rgb", 0.5)
    )  # 15 m: its own cell centre is 0 m away, still seen
    monitor.report(status("b.thermal", 0.0))  # another sensor: ignored
    assert monitor.percent() == pytest.approx(50.0)
    monitor.report(status("b.rgb", 0.0))
    assert monitor.percent() == pytest.approx(25.0)


def test_a_status_is_sent_first_and_then_only_on_change() -> None:
    monitor = small(1, warning=60.0)
    first = monitor.update(0.0)
    assert (first.coverage_pct, first.warning) == (50.0, True)
    assert monitor.update(1.0) is None
    monitor.report(status("a.rgb", 0.5))
    assert monitor.update(2.0) is None  # same figure
    monitor.report(status("b.rgb", 0.0))
    assert monitor.update(3.0).coverage_pct == pytest.approx(25.0)


def site_monitor(site: SiteConfig) -> CoverageMonitor:
    return CoverageMonitor(
        site.coverage,
        site.zones,
        {s.id: s.position_enu_m for s in site.stations},
        site.sensors[site.coverage.sensor].base_range_m[site.coverage.design_target],
    )


def test_clear_air_covers_the_whole_important_zone(site: SiteConfig) -> None:
    clear = site_monitor(site).update(0.0)
    assert (clear.coverage_pct, clear.warning) == (100.0, False)


def test_dust_at_half_visibility_drops_below_80_percent(site: SiteConfig) -> None:
    monitor = site_monitor(site)
    for station in site.stations:
        monitor.report(status(f"{station.id}.rgb", 0.5))
    dusty = monitor.update(1.0)
    assert dusty.coverage_pct < 80.0
    assert dusty.warning
