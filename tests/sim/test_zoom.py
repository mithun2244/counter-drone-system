"""Zoom cameras in the simulator: when a task applies, what is seen, and what it may change.

A fake look source stands in for recorded media, so these run without models.
"""

import pytest

from cuas.config import SiteConfig
from cuas.geometry import bearing_to
from cuas.schemas import BearingDetection, Track, TrackClass, ZoomTask
from cuas.sim.scenario import Environment
from cuas.sim.station import Look
from cuas.sim.zoom import ZoomSim

TARGET = (0.0, 600.0, 80.0)
WIDE = {"drone": 0.2, "bird": 0.8}
ZOOMED = {"drone": 0.9, "bird": 0.1}


class FakeLooks:
    """Answers every camera with a fixed look, and records what zoom asked for."""

    def __init__(self, zoom_answers: bool = True) -> None:
        self.zoom_asked: list[tuple[str, float]] = []
        self._zoom_answers = zoom_answers

    def look(self, station_id, sensor, target_id, target_type, range_m, t):
        frame = f"{station_id}:{sensor}:{round(t / 0.2)}"
        if sensor == "zoom":
            self.zoom_asked.append((target_id, range_m))
            return Look(dict(ZOOMED), frame) if self._zoom_answers else None
        return None if sensor == "acoustic" else Look(dict(WIDE), frame)

    def hear_engine(self, picket_id, target_id, target_type, range_m, t):
        return None


def zoom_sim(site: SiteConfig, media: FakeLooks) -> ZoomSim:
    return ZoomSim(site, Environment(visibility_factor=1.0, wind_mps=0.0), 1, media)


def aimed_at(site: SiteConfig, at, t: float) -> ZoomTask:
    azimuth, elevation, _ = bearing_to(site.stations[0].position_enu_m, at)
    return ZoomTask(
        station_id="st1",
        t=t,
        camera_id="z1",
        track_id="trk-1",
        azimuth_deg=azimuth,
        elevation_deg=elevation,
    )


def seen(zoom: ZoomSim, at, ticks: range) -> list[BearingDetection]:
    """Zoom bearings on one target over several ticks, each 0.2 s apart."""
    out = []
    for k in ticks:
        zoom.point(k * 0.2)
        out += [b for b, _ in zoom.observe("quad-1", "quadcopter", at, k * 0.2)]
    return out


def test_a_task_takes_effect_one_scheduler_period_after_it_is_issued(
    site: SiteConfig,
) -> None:
    zoom = zoom_sim(site, FakeLooks())
    zoom.task(aimed_at(site, TARGET, 1.0))
    assert site.zoom.period_s == 0.6
    assert seen(zoom, TARGET, range(5, 8)) == []  # 1.0 to 1.4 s
    assert {round(b.t, 1) for b in seen(zoom, TARGET, range(8, 20))} >= {1.6}


def test_only_a_target_inside_the_narrow_view_is_seen(site: SiteConfig) -> None:
    zoom = zoom_sim(site, FakeLooks())
    zoom.task(aimed_at(site, TARGET, 0.0))
    beside = (40.0, 600.0, 80.0)  # about 7 degrees off the camera's aim
    assert seen(zoom, beside, range(3, 30)) == []
    assert seen(zoom, TARGET, range(30, 60))


def test_zoom_asks_for_a_look_as_if_magnification_times_closer(
    site: SiteConfig,
) -> None:
    media = FakeLooks()
    zoom = zoom_sim(site, media)
    zoom.task(aimed_at(site, TARGET, 0.0))
    [bearing, *_] = seen(zoom, TARGET, range(3, 30))
    _, _, range_m = bearing_to(site.stations[0].position_enu_m, TARGET)
    assert media.zoom_asked[0] == ("quad-1", pytest.approx(range_m / 4.0))
    assert (bearing.sensor, bearing.class_probs) == ("zoom", ZOOMED)
    assert bearing.sigma_deg == pytest.approx(site.sensors["rgb"].sigma_deg / 4.0)


def test_no_look_means_the_zoom_camera_reports_nothing(site: SiteConfig) -> None:
    zoom = zoom_sim(site, FakeLooks(zoom_answers=False))
    zoom.task(aimed_at(site, TARGET, 0.0))
    assert seen(zoom, TARGET, range(3, 30)) == []


def dumps(messages) -> list[str]:
    return [m.model_dump_json() for m in messages]


def of_type(messages, kind) -> list:
    return [m for m in messages if isinstance(m, kind)]


async def test_without_recorded_media_zoom_tasks_change_nothing(
    record_pipeline,
) -> None:
    sensed, _, controlled, _ = await record_pipeline("s2", seed=1, zoom=2)
    assert of_type(controlled, ZoomTask)
    assert not [m for m in of_type(sensed, BearingDetection) if m.sensor == "zoom"]


async def test_zoom_looks_reach_the_classifier_and_never_move_a_track(
    record_pipeline,
) -> None:
    runs = {
        n: await record_pipeline("s2", seed=1, media=FakeLooks(), zoom=n)
        for n in (0, 1, 2)
    }
    tracks = {n: dumps(of_type(run[2], Track)) for n, run in runs.items()}
    assert tracks[0] == tracks[1] == tracks[2]
    for n, (sensed, _, controlled, _) in runs.items():
        zoom_bearings = [
            m for m in of_type(sensed, BearingDetection) if m.sensor == "zoom"
        ]
        zoom_looks = [
            c
            for c in of_type(controlled, TrackClass)
            if c.evidence.look == pytest.approx(ZOOMED["drone"])
        ]
        assert bool(zoom_bearings) is (n > 0)
        assert bool(zoom_looks) is (n > 0)


async def test_zoom_feedback_is_the_same_fast_or_paced(record_pipeline) -> None:
    fast = await record_pipeline("s2", seed=1, media=FakeLooks(), zoom=1)
    paced = await record_pipeline("s2", seed=1, media=FakeLooks(), zoom=1, pace=60.0)
    assert [m for m in of_type(fast[0], BearingDetection) if m.sensor == "zoom"]
    assert dumps(fast[0]) == dumps(paced[0])
    assert dumps(fast[2]) == dumps(paced[2])
