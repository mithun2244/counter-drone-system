"""Batching and routing between the gateway's output and the trackers."""

import pytest

from cuas.config import SiteConfig, ZoneLabels
from cuas.control.layer import ControlLayer
from cuas.geometry import bearing_to
from cuas.schemas import (
    BearingDetection,
    Message,
    PicketAlert,
    SectorTrack,
    SensorStatus,
    Track,
)

TARGET = (300.0, 900.0, 80.0)
TICK = 0.2


@pytest.fixture
def layer(site: SiteConfig) -> ControlLayer:
    return ControlLayer(site, ZoneLabels(critical="c", important="i", perimeter="p"))


def bearings(site: SiteConfig, t: float, sensors=("rgb", "thermal"), target=TARGET):
    found = []
    for station in site.stations:
        azimuth, elevation, _ = bearing_to(station.position_enu_m, target)
        for sensor in sensors:
            found.append(
                BearingDetection(
                    station_id=station.id,
                    sensor=sensor,
                    t=t,
                    azimuth_deg=azimuth,
                    elevation_deg=elevation,
                    sigma_deg=site.sensors[sensor].sigma_deg,
                )
            )
    return found


def status(t: float) -> SensorStatus:
    return SensorStatus(sensor_id="st1.rgb", ok=True, visibility_factor=1.0, t=t)


def feed(layer: ControlLayer, messages: list[Message]) -> list[Message]:
    return [out for message in messages for out in layer.ingest(message)]


def test_a_batch_waits_for_a_later_message_and_flush_ends_it(
    layer: ControlLayer, site: SiteConfig
) -> None:
    assert feed(layer, bearings(site, 0.0)) == []
    first = feed(layer, bearings(site, TICK))
    assert [m.t for m in first if isinstance(m, Track)] == [0.0]
    last = layer.flush()
    assert [m.t for m in last if isinstance(m, Track)] == [TICK]
    assert layer.flush() == []


def test_a_picket_alert_becomes_a_wedge_at_once(
    layer: ControlLayer, site: SiteConfig
) -> None:
    alert = PicketAlert(
        picket_id="pk4", t=5.0, bearing_deg=300.0, loudness=0.5, engine_type_probs={}
    )
    [wedge] = layer.ingest(alert)
    assert isinstance(wedge, SectorTrack)
    assert wedge.origin_enu_m == site.pickets[3].position_enu_m
    assert wedge.half_width_deg == site.picket_settings.bearing_error_deg


def test_heard_but_not_seen_gives_wedges_and_never_a_track(
    layer: ControlLayer, site: SiteConfig
) -> None:
    out = []
    for k in range(20):
        out += feed(layer, bearings(site, k * TICK, sensors=("acoustic",)))
    out += layer.flush()
    assert out
    assert not [m for m in out if isinstance(m, Track)]
    wedges = [m for m in out if isinstance(m, SectorTrack)]
    assert {w.sensor_id for w in wedges} == {
        "st1.acoustic",
        "st2.acoustic",
        "st3.acoustic",
    }
    assert {w.half_width_deg for w in wedges} == {
        site.tracker.acoustic_sector_sigmas * site.sensors["acoustic"].sigma_deg
    }


def test_an_acoustic_bearing_on_a_3d_track_makes_no_wedge(
    layer: ControlLayer, site: SiteConfig
) -> None:
    out = []
    for k in range(6):
        out += feed(
            layer, bearings(site, k * TICK, sensors=("rgb", "thermal", "acoustic"))
        )
    out += layer.flush()
    assert not [m for m in out if isinstance(m, SectorTrack)]
    assert [m for m in out if isinstance(m, Track)]


def test_statuses_keep_time_moving_so_an_unseen_track_is_lost(
    layer: ControlLayer, site: SiteConfig
) -> None:
    out = []
    for k in range(3):
        out += feed(layer, bearings(site, k * TICK))
    for second in range(1, 6):
        out += feed(layer, [status(float(second))])
    out += layer.flush()
    statuses = [m.status for m in out if isinstance(m, Track)]
    assert statuses[-1] == "lost"
    assert statuses.count("lost") == 1
