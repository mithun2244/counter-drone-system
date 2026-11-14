"""Big-drone camera cues (src/cuas/dashboard/cues.py): acoustic -> camera -> zoom, from bus
messages only, and never for small drones."""

import pytest

from cuas.config import SiteConfig, ZoneLabels
from cuas.dashboard.cues import CueTracker
from cuas.dashboard.frames import FrameBuilder, replay
from cuas.geometry import bearing_to
from cuas.schemas import (
    BearingDetection,
    PicketAlert,
    RejectedMessage,
    SectorTrack,
    ThreatAssessment,
    Track,
    ZoomTask,
)

PK4 = (2121.3, -2121.3, 3.0)
LABELS = ZoneLabels(critical="Unit", important="Area", perimeter="Perimeter")


def heard(t: float, piston: float = 0.9) -> list:
    return [
        PicketAlert(
            picket_id="pk4",
            t=t,
            bearing_deg=135.0,
            loudness=0.5,
            engine_type_probs={"piston": piston, "electric": 1.0 - piston},
        ),
        SectorTrack(
            sector_id="sec-1",
            t=t,
            sensor_id="pk4",
            origin_enu_m=PK4,
            bearing_deg=135.0,
            half_width_deg=20.0,
            reports=1,
            status="active",
        ),
    ]


def ray(t: float, azimuth: float, station: str = "st2") -> BearingDetection:
    return BearingDetection(
        station_id=station,
        sensor="thermal",
        t=t,
        azimuth_deg=azimuth,
        elevation_deg=1.5,
        sigma_deg=0.1,
    )


def confirmed(t: float, position: tuple[float, float, float]) -> Track:
    cov = tuple(tuple(float(i == j) for j in range(6)) for i in range(6))
    return Track(
        track_id="trk-1",
        t=t,
        position_enu_m=position,
        velocity_mps=(-40.0, 30.0, 0.0),
        covariance=cov,
        n_stations=2,
        status="confirmed",
    )


def cue_azimuth(site: SiteConfig, station: str = "st2") -> float:
    position = next(s.position_enu_m for s in site.stations if s.id == station)
    return bearing_to(position, PK4)[0]


def feed(cues: CueTracker, *messages) -> None:
    for message in messages:
        cues.ingest(message)


def test_a_piston_engine_cues_the_nearest_camera_then_a_ray_near_it_detects(
    site: SiteConfig,
) -> None:
    cues = CueTracker(site)
    feed(cues, *heard(10.0))
    (cue,) = cues.views({}, [], {})
    assert (cue.stage, cue.cue_station_id, cue.views) == ("acoustic", "st2", [])
    assert cue.cue_bearing_deg == pytest.approx(cue_azimuth(site))
    half = site.dashboard.camera_cue.search_half_width_deg
    feed(cues, ray(5.0, cue_azimuth(site)))  # before the engine was heard: not this one
    feed(cues, ray(11.0, cue_azimuth(site) + half + 5.0))  # outside the search
    assert cues.views({}, [], {})[0].stage == "acoustic" and not cues.take_notes()
    feed(cues, ray(12.0, cue_azimuth(site) - 20.0))
    (cue,) = cues.views({}, [], {})
    (note,) = cues.take_notes()
    assert (cue.stage, cue.detected_t, cue.detected_by) == ("camera", 12.0, "st2")
    assert (note.picket_id, note.station_id, note.t) == ("pk4", "st2", 12.0)
    (wide,) = cue.views
    assert (
        wide.camera == "wide" and wide.range_m is None
    )  # no track yet: one bearing only
    assert wide.pointing_azimuth_deg == pytest.approx(cue_azimuth(site))
    assert wide.seen_azimuth_deg == pytest.approx(cue_azimuth(site) - 20.0)
    feed(cues, ray(12.2, cue_azimuth(site) - 19.8))  # the same target, moved on
    assert not cues.take_notes()
    assert cues.views({}, [], {})[0].views[0].seen_azimuth_deg == pytest.approx(
        cue_azimuth(site) - 19.8
    )


def test_a_confirmed_track_near_the_picket_links_then_zoom_takes_over(
    site: SiteConfig,
) -> None:
    cues = CueTracker(site)
    feed(cues, *heard(10.0), ray(12.0, cue_azimuth(site) - 10.0))
    near = (1500.0, -1300.0, 90.0)  # within reach of pk4
    track = confirmed(30.0, near)
    feed(cues, track)
    threat = ThreatAssessment(
        track_id="trk-1",
        t=30.0,
        score=0.9,
        level="red",
        zone="critical",
        time_to_impact_s=40.0,
        reasons=("engine heard",),
        alert_id="alert-1",
    )
    (cue,) = cues.views({"trk-1": track}, [], {"trk-1": threat})
    (wide,) = cue.views
    azimuth, elevation, range_m = bearing_to(
        next(s.position_enu_m for s in site.stations if s.id == "st2"), near
    )
    assert (cue.stage, cue.track_id, cue.alert_id) == ("camera", "trk-1", "alert-1")
    assert wide.range_m == pytest.approx(range_m)
    assert wide.pointing_azimuth_deg == pytest.approx(azimuth)  # slewed onto the track
    task = ZoomTask(
        station_id="st3",
        t=31.0,
        camera_id="zoom-1",
        track_id="trk-1",
        azimuth_deg=100.0,
        elevation_deg=elevation,
    )
    (cue,) = cues.views({"trk-1": track}, [task], {"trk-1": threat})
    assert cue.stage == "zoom" and [v.camera for v in cue.views] == ["wide", "zoom"]
    zoom = cue.views[1]
    assert zoom.fov_deg == pytest.approx(2.0 * site.zoom.half_fov_deg)
    assert zoom.station_id == "st3" and zoom.pointing_azimuth_deg == 100.0
    assert zoom.fov_deg < wide.fov_deg


def test_a_track_far_from_the_picket_or_unconfirmed_does_not_link(
    site: SiteConfig,
) -> None:
    cues = CueTracker(site)
    feed(cues, *heard(10.0), ray(12.0, cue_azimuth(site)))
    reach = site.dashboard.camera_cue.link_reach_factor * max(
        e.hearing_radius_m for e in site.picket_settings.engines.values()
    )
    far = confirmed(30.0, (PK4[0] - reach - 100.0, PK4[1], 90.0))
    tentative = confirmed(30.0, (1500.0, -1300.0, 90.0)).model_copy(
        update={"status": "tentative"}
    )
    feed(cues, far, tentative)
    assert cues.views({}, [], {})[0].track_id is None


def test_an_electric_engine_starts_nothing(site: SiteConfig) -> None:
    cues = CueTracker(site)
    feed(cues, *heard(10.0, piston=0.1), ray(12.0, cue_azimuth(site)))
    assert cues.views({}, [], {}) == [] and cues.take_notes() == []


async def frames_of(record_pipeline, site: SiteConfig, scenario: str) -> list:
    _, ingested, controlled, _ = await record_pipeline(scenario)
    accepted = [m for m in ingested if not isinstance(m, RejectedMessage)]
    return replay(FrameBuilder("run", site, LABELS), accepted, controlled)


async def test_s1_goes_acoustic_then_camera_then_zoom_in_that_order(
    record_pipeline, site: SiteConfig
) -> None:
    frames = await frames_of(record_pipeline, site, "s1")
    first: dict[tuple[str, str], float] = {}
    for frame in frames:
        for cue in frame.cues:
            first.setdefault((cue.cue_id, cue.stage), frame.t)
    zoomed = {cue for cue, stage in first if stage == "zoom"}
    heard_first = {cue for cue in zoomed if (cue, "acoustic") in first}
    assert heard_first, "some engagement goes all the way from a picket to the zoom"
    for cue_id in heard_first:
        assert (
            first[(cue_id, "acoustic")]
            < first[(cue_id, "camera")]
            < first[(cue_id, "zoom")]
        )
    detected = {c.cue_id: c.detected_t for f in frames for c in f.cues}
    for cue_id in (
        zoomed - heard_first
    ):  # another drone of the wave: starts at its track
        assert detected[cue_id] is not None
        assert detected[cue_id] <= first[(cue_id, "zoom")]
    camera_first = min(t for (_, stage), t in first.items() if stage == "camera")
    track_first = min(f.t for f in frames if any(tr.status for tr in f.tracks))
    assert camera_first < track_first  # the camera sees it before any track exists
    alerted = {a.alert_id for f in frames for a in f.alerts}
    with_cue = {c.alert_id for f in frames for c in f.cues if c.alert_id}
    assert alerted and alerted == with_cue  # every S1 alert gets its camera sequence


@pytest.mark.parametrize("scenario", ["s2", "s3", "s4"])
async def test_small_drone_scenarios_never_get_a_cue(
    record_pipeline, site: SiteConfig, scenario: str
) -> None:
    frames = await frames_of(record_pipeline, site, scenario)
    assert not any(f.cues for f in frames)
