import pytest

from cuas.control.sectors import SectorTracker

PK4 = (2121.3, -2121.3, 3.0)
LOST_AFTER = 6.0


@pytest.fixture
def sectors() -> SectorTracker:
    return SectorTracker(LOST_AFTER)


def test_a_report_starts_a_wedge_from_the_sensor(sectors: SectorTracker) -> None:
    wedge = sectors.report("pk4", PK4, 10.0, 300.0, 20.0)
    assert (wedge.sector_id, wedge.sensor_id, wedge.origin_enu_m) == (
        "sec-1",
        "pk4",
        PK4,
    )
    assert (wedge.bearing_deg, wedge.half_width_deg, wedge.reports) == (300.0, 20.0, 1)
    assert wedge.status == "active"


def test_a_nearby_report_refreshes_the_same_wedge(sectors: SectorTracker) -> None:
    sectors.report("pk4", PK4, 10.0, 300.0, 20.0)
    again = sectors.report("pk4", PK4, 12.0, 335.0, 20.0)
    assert (again.sector_id, again.bearing_deg, again.reports, again.t) == (
        "sec-1",
        335.0,
        2,
        12.0,
    )


def test_wrapping_across_north_still_counts_as_nearby(sectors: SectorTracker) -> None:
    sectors.report("pk1", (0.0, 3000.0, 3.0), 1.0, 355.0, 20.0)
    assert (
        sectors.report("pk1", (0.0, 3000.0, 3.0), 2.0, 10.0, 20.0).sector_id == "sec-1"
    )


def test_another_direction_or_another_sensor_starts_its_own_wedge(
    sectors: SectorTracker,
) -> None:
    sectors.report("pk4", PK4, 10.0, 300.0, 20.0)
    assert sectors.report("pk4", PK4, 10.0, 120.0, 20.0).sector_id == "sec-2"
    assert (
        sectors.report("pk5", (0.0, -3000.0, 3.0), 10.0, 300.0, 20.0).sector_id
        == "sec-3"
    )


def test_a_silent_wedge_is_announced_lost_once(sectors: SectorTracker) -> None:
    sectors.report("pk4", PK4, 10.0, 300.0, 20.0)
    assert sectors.expire(10.0 + LOST_AFTER) == []
    lost = sectors.expire(10.0 + LOST_AFTER + 0.2)
    assert [(s.sector_id, s.status) for s in lost] == [("sec-1", "lost")]
    assert sectors.expire(30.0) == []
