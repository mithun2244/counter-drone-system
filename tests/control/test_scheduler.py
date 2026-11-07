"""Zoom scheduling on synthetic tracks: priority, reach, dwell and pre-emption."""

import pytest

from cuas.config import SiteConfig
from cuas.control.scheduler import ZoomScheduler
from cuas.geometry import bearing_to
from cuas.schemas import SensorStatus, Track


def scheduler(site: SiteConfig, per_station: int = 1) -> ZoomScheduler:
    return ZoomScheduler(
        site.zoom,
        per_station,
        {s.id: s.position_enu_m for s in site.stations},
        "rgb",
        site.sensors["rgb"].base_range_m["quadcopter"],
    )


def track(track_id: str, at, status: str = "confirmed") -> Track:
    cov = tuple(tuple(1.0 if i == j else 0.0 for j in range(6)) for i in range(6))
    return Track(
        track_id=track_id,
        t=0.0,
        position_enu_m=at,
        velocity_mps=(0.0, 0.0, 0.0),
        covariance=cov,
        n_stations=3,
        status=status,
    )


NEAR_ST1 = (0.0, 400.0, 80.0)
NEAR_ST2 = (300.0, -250.0, 80.0)
NEAR_ST3 = (-300.0, -250.0, 80.0)


def duties(tasks) -> dict[str, str]:
    return {task.track_id: f"{task.station_id}.{task.camera_id}" for task in tasks}


def test_no_zoom_cameras_means_no_tasks(site: SiteConfig) -> None:
    assert (
        scheduler(site, 0).update(0.0, [track("trk-1", NEAR_ST1)], {"trk-1": 0.9}) == []
    )


def test_the_nearest_camera_takes_a_track_and_points_at_it(site: SiteConfig) -> None:
    [task] = scheduler(site).update(0.0, [track("trk-1", NEAR_ST1)], {"trk-1": 0.9})
    assert (task.station_id, task.camera_id, task.track_id) == ("st1", "z1", "trk-1")
    azimuth, elevation, _ = bearing_to(site.stations[0].position_enu_m, NEAR_ST1)
    assert (task.azimuth_deg, task.elevation_deg) == pytest.approx((azimuth, elevation))


def test_only_confirmed_tracks_get_a_camera(site: SiteConfig) -> None:
    tasks = scheduler(site).update(
        0.0, [track("trk-1", NEAR_ST1, "tentative")], {"trk-1": 0.9}
    )
    assert tasks == []


def test_more_tracks_than_cameras_go_by_score(site: SiteConfig) -> None:
    """Three cameras, four tracks at one spot: the three highest scores win."""
    tracks = [track(f"trk-{i}", NEAR_ST1) for i in range(1, 5)]
    scores = {"trk-1": 0.2, "trk-2": 0.9, "trk-3": 0.5, "trk-4": 0.7}
    assert set(duties(scheduler(site).update(0.0, tracks, scores))) == {
        "trk-2",
        "trk-4",
        "trk-3",
    }


def test_a_track_out_of_reach_gets_nothing(site: SiteConfig) -> None:
    far = (20000.0, 0.0, 80.0)
    assert scheduler(site).update(0.0, [track("trk-1", far)], {"trk-1": 0.9}) == []


def test_dust_shortens_the_reach(site: SiteConfig) -> None:
    zoom = scheduler(site)
    for station in site.stations:
        zoom.report(
            SensorStatus(
                sensor_id=f"{station.id}.rgb", ok=True, visibility_factor=0.1, t=0.0
            )
        )
    assert zoom.update(0.0, [track("trk-1", (0.0, 1200.0, 80.0))], {"trk-1": 0.9}) == []


def one_camera(site: SiteConfig) -> ZoomScheduler:
    """Every station but st1 is blinded, so trk-1 and trk-2 compete for st1.z1."""
    zoom = scheduler(site)
    for station in site.stations[1:]:
        zoom.report(
            SensorStatus(
                sensor_id=f"{station.id}.rgb", ok=True, visibility_factor=0.0, t=0.0
            )
        )
    return zoom


def test_a_camera_dwells_unless_a_much_higher_score_needs_it(site: SiteConfig) -> None:
    zoom = one_camera(site)
    both = [track("trk-1", NEAR_ST1), track("trk-2", NEAR_ST1)]
    assert duties(zoom.update(0.0, both, {"trk-1": 0.5, "trk-2": 0.3})) == {
        "trk-1": "st1.z1"
    }
    # trk-2 now scores a little more: not enough to cut the 3 s dwell short
    assert duties(zoom.update(0.6, both, {"trk-1": 0.5, "trk-2": 0.6})) == {
        "trk-1": "st1.z1"
    }
    # after the dwell, the higher score takes the camera
    assert duties(zoom.update(3.0, both, {"trk-1": 0.5, "trk-2": 0.6})) == {
        "trk-2": "st1.z1"
    }


def test_a_much_higher_score_takes_the_camera_at_once(site: SiteConfig) -> None:
    zoom = one_camera(site)
    both = [track("trk-1", NEAR_ST1), track("trk-2", NEAR_ST1)]
    zoom.update(0.0, both, {"trk-1": 0.5, "trk-2": 0.1})
    assert duties(zoom.update(0.6, both, {"trk-1": 0.5, "trk-2": 0.7})) == {
        "trk-2": "st1.z1"
    }


def test_it_runs_once_per_period(site: SiteConfig) -> None:
    zoom = scheduler(site)
    assert zoom.update(0.0, [track("trk-1", NEAR_ST1)], {"trk-1": 0.9})
    assert zoom.update(0.2, [track("trk-1", NEAR_ST1)], {"trk-1": 0.9}) == []
    assert zoom.update(0.6, [track("trk-1", NEAR_ST1)], {"trk-1": 0.9})


def test_a_lost_track_frees_its_camera(site: SiteConfig) -> None:
    zoom = one_camera(site)
    zoom.update(0.0, [track("trk-1", NEAR_ST1)], {"trk-1": 0.9})
    tasks = zoom.update(0.6, [track("trk-2", NEAR_ST1)], {"trk-2": 0.1})
    assert duties(tasks) == {"trk-2": "st1.z1"}


def test_two_cameras_per_station_are_named_z1_and_z2(site: SiteConfig) -> None:
    tracks = [track("trk-1", NEAR_ST1), track("trk-2", NEAR_ST1)]
    tasks = scheduler(site, 2).update(0.0, tracks, {"trk-1": 0.9, "trk-2": 0.8})
    assert sorted(duties(tasks).values()) == ["st1.z1", "st1.z2"]
