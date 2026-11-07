"""The shared tracker on exact synthetic bearings, with no simulator involved."""

import logging

import numpy as np
import pytest

from cuas.config import SiteConfig
from cuas.control.tracker import SharedTracker
from cuas.control.triangulation import Fix, NoFix, Ray, triangulate
from cuas.geometry import bearing_to
from cuas.schemas import BearingDetection, Track

TICK = 0.2
ALL = ("st1", "st2", "st3")
TARGET = (300.0, 900.0, 80.0)


@pytest.fixture
def tracker(site: SiteConfig) -> SharedTracker:
    return SharedTracker(site.tracker, stations(site))


def stations(site: SiteConfig) -> dict[str, tuple[float, float, float]]:
    return {s.id: s.position_enu_m for s in site.stations}


def seen_by(
    site: SiteConfig,
    target,
    t: float,
    at=ALL,
    sensors=("rgb", "thermal"),
    **extra: object,
) -> list[BearingDetection]:
    """Exact bearings from each named station and sensor to the target."""
    found = []
    for station_id in at:
        azimuth, elevation, _ = bearing_to(stations(site)[station_id], target)
        for sensor in sensors:
            found.append(
                BearingDetection(
                    station_id=station_id,
                    sensor=sensor,
                    t=t,
                    azimuth_deg=azimuth,
                    elevation_deg=elevation,
                    sigma_deg=site.sensors[sensor].sigma_deg,
                    **extra,
                )
            )
    return found


def run(tracker: SharedTracker, batches) -> list[list[Track]]:
    return [tracker.update(t, bearings) for t, bearings in batches]


def confirm(tracker: SharedTracker, site: SiteConfig, target=TARGET) -> float:
    """Three 3-station fixes, which confirm a track. Returns the last time used."""
    outputs = run(
        tracker, [(k * TICK, seen_by(site, target, k * TICK)) for k in range(3)]
    )
    assert [t.status for t in outputs[-1]] == ["confirmed"]
    return 2 * TICK


def rays(site: SiteConfig, bearings: list[BearingDetection]) -> list[Ray]:
    return [Ray.from_bearing(b, stations(site)[b.station_id]) for b in bearings]


def test_a_single_station_starts_nothing(
    tracker: SharedTracker, site: SiteConfig
) -> None:
    for k in range(10):
        assert (
            tracker.update(k * TICK, seen_by(site, TARGET, k * TICK, at=("st1",))) == []
        )


def test_two_stations_alone_confirm_a_target(
    tracker: SharedTracker, site: SiteConfig
) -> None:
    outputs = run(
        tracker,
        [
            (k * TICK, seen_by(site, TARGET, k * TICK, at=("st1", "st2")))
            for k in range(3)
        ],
    )
    assert [[t.status for t in out] for out in outputs] == [
        ["tentative"],
        ["tentative"],
        ["confirmed"],
    ]
    final = outputs[-1][0]
    assert final.track_id == "trk-1"
    assert final.n_stations == 2
    assert final.position_enu_m == pytest.approx(TARGET, abs=1e-3)


def test_a_lone_station_neither_moves_nor_refreshes_a_track(
    tracker: SharedTracker, site: SiteConfig
) -> None:
    last_fix = confirm(tracker, site)
    fixed = None
    k = 3
    while True:
        out = tracker.update(k * TICK, seen_by(site, TARGET, k * TICK, at=("st1",)))
        if k * TICK - last_fix <= site.tracker.lost_after_s:
            assert [(t.status, t.n_stations) for t in out] == [("confirmed", 0)]
            fixed = fixed or out[0].position_enu_m
            assert out[0].position_enu_m == pytest.approx(fixed, abs=1e-6)
        else:
            assert [t.status for t in out] == ["lost"]
            break
        k += 1
    assert (
        tracker.update(
            (k + 1) * TICK, seen_by(site, TARGET, (k + 1) * TICK, at=("st1",))
        )
        == []
    )


def test_near_parallel_rays_start_nothing(
    tracker: SharedTracker, site: SiteConfig
) -> None:
    far = (0.0, 3200.0, 80.0)
    assert triangulate(rays(site, seen_by(site, far, 0.0)), site.tracker) == NoFix(
        "parallel"
    )
    for k in range(10):
        assert tracker.update(k * TICK, seen_by(site, far, k * TICK)) == []


X, Y = (400.0, 900.0, 80.0), (-300.0, 1000.0, 120.0)


def test_a_contested_two_station_fix_starts_nothing(
    tracker: SharedTracker, site: SiteConfig
) -> None:
    """Two targets seen by the same two stations: four pairings, and nothing to tell them apart."""
    for k in range(5):
        t = k * TICK
        both = seen_by(site, X, t, at=("st1", "st2")) + seen_by(
            site, Y, t, at=("st1", "st2")
        )
        assert tracker.update(t, both) == []
    for k in range(5, 8):
        t = k * TICK
        out = tracker.update(t, seen_by(site, X, t) + seen_by(site, Y, t))
    assert sorted(t.status for t in out) == ["confirmed", "confirmed"]


def test_rays_crossing_where_nothing_is_never_become_a_track(
    tracker: SharedTracker, site: SiteConfig
) -> None:
    """Level rays from every station meet everywhere in one plane, so ghosts are guaranteed."""
    level_x, level_y = (400.0, 900.0, 15.0), (-300.0, 1000.0, 15.0)
    ghost = [
        seen_by(site, level_x, 0.0, at=("st1",))[0],
        seen_by(site, level_y, 0.0, at=("st2",))[0],
    ]
    assert isinstance(triangulate(rays(site, ghost), site.tracker), Fix)
    ever: set[str] = set()
    for k in range(10):
        t = k * TICK
        out = tracker.update(t, seen_by(site, level_x, t) + seen_by(site, level_y, t))
        ever |= {track.track_id for track in out}
    assert ever == {"trk-1", "trk-2"}  # not even a tentative ghost, on any tick
    found = sorted(out, key=lambda track: track.position_enu_m[0])
    assert [t.status for t in found] == ["confirmed", "confirmed"]
    assert found[0].position_enu_m == pytest.approx(level_y, abs=1e-3)
    assert found[1].position_enu_m == pytest.approx(level_x, abs=1e-3)


def test_a_fix_close_to_a_track_updates_it_instead_of_starting_another(
    tracker: SharedTracker, site: SiteConfig
) -> None:
    last = confirm(tracker, site)
    jumped = np.add(TARGET, (25.0, 0.0, 0.0))
    out = tracker.update(last + TICK, seen_by(site, jumped, last + TICK))
    assert [(t.track_id, t.n_stations) for t in out] == [("trk-1", 3)]
    far = np.add(TARGET, (200.0, 0.0, 0.0))
    out = tracker.update(last + 2 * TICK, seen_by(site, far, last + 2 * TICK))
    assert sorted(t.track_id for t in out) == ["trk-1", "trk-2"]


def test_three_corroborated_fixes_must_fall_within_the_window(
    tracker: SharedTracker, site: SiteConfig
) -> None:
    statuses = [
        [t.status for t in tracker.update(t, seen_by(site, TARGET, t))]
        for t in (0.0, 1.6, 3.2, 3.4)
    ]
    assert statuses == [["tentative"], ["tentative"], ["tentative"], ["confirmed"]]


def test_class_data_and_snapshots_do_not_change_tracks(site: SiteConfig) -> None:
    plain, labelled = (SharedTracker(site.tracker, stations(site)) for _ in range(2))
    extra = {"class_probs": {"drone": 0.9, "bird": 0.1}, "snapshot_ref": "abcd:1"}
    for k in range(6):
        t = k * TICK
        a = plain.update(t, seen_by(site, TARGET, t))
        b = labelled.update(t, seen_by(site, TARGET, t, **extra))
        assert [m.model_dump_json() for m in a] == [m.model_dump_json() for m in b]


def test_acoustic_bearings_never_place_a_target(
    tracker: SharedTracker, site: SiteConfig
) -> None:
    for k in range(10):
        assert (
            tracker.update(
                k * TICK, seen_by(site, TARGET, k * TICK, sensors=("acoustic",))
            )
            == []
        )


def test_a_live_track_accounts_for_a_matching_acoustic_bearing(
    tracker: SharedTracker, site: SiteConfig
) -> None:
    confirm(tracker, site)
    heard = seen_by(site, TARGET, 0.4, at=("st2",), sensors=("acoustic",))[0]
    assert tracker.accounts_for(heard)
    away = heard.model_copy(update={"azimuth_deg": (heard.azimuth_deg + 90.0) % 360.0})
    assert not tracker.accounts_for(away)


def test_a_late_batch_is_ignored(
    tracker: SharedTracker, site: SiteConfig, caplog: pytest.LogCaptureFixture
) -> None:
    confirm(tracker, site)
    with caplog.at_level(logging.WARNING, logger="cuas.control.tracker"):
        assert tracker.update(0.2, seen_by(site, TARGET, 0.2)) == []
    assert "ignored a batch" in caplog.text


def test_a_moving_target_is_followed_with_its_velocity(
    tracker: SharedTracker, site: SiteConfig
) -> None:
    velocity = np.array([-50.0, -10.0, 0.0])
    start = np.array([900.0, 600.0, 100.0])
    for k in range(25):
        t = k * TICK
        out = tracker.update(t, seen_by(site, start + velocity * t, t))
    assert [x.track_id for x in out] == ["trk-1"]
    assert out[0].position_enu_m == pytest.approx(start + velocity * 24 * TICK, abs=0.1)
    assert out[0].velocity_mps == pytest.approx(velocity, abs=0.5)
