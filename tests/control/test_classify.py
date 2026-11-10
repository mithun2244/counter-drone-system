"""Hand-calculated fusion, and clue matching on synthetic tracks and bearings."""

import math

import pytest

from cuas.config import SiteConfig
from cuas.control.classify import (
    Classifier,
    fuse,
    look_probability,
    piston_share,
    sound_probability,
)
from cuas.geometry import bearing_to
from cuas.schemas import BearingDetection, HeardBearing, PicketAlert, Track

WEIGHTS = {"look": 1.0, "move": 1.0, "sound": 1.0}
FLOOR = 0.02
TARGET = (300.0, 900.0, 80.0)
OTHER = (-600.0, 400.0, 60.0)


def test_one_clue_alone_gives_its_own_probability() -> None:
    assert fuse(
        0.1, {"look": None, "move": 0.8, "sound": None}, WEIGHTS, FLOOR
    ) == pytest.approx(0.8)


def test_two_clues_add_in_log_odds() -> None:
    """logit = logit(0.1) + (logit(0.8) - logit(0.1)) + (logit(0.9) - logit(0.1)) = 5.7807."""
    p = fuse(0.1, {"look": None, "move": 0.8, "sound": 0.9}, WEIGHTS, FLOOR)
    assert p == pytest.approx(1.0 / (1.0 + math.exp(-5.78074)), abs=1e-5)


def test_missing_clues_leave_the_prior() -> None:
    assert fuse(
        0.1, {"look": None, "move": None, "sound": None}, WEIGHTS, FLOOR
    ) == pytest.approx(0.1)


def test_no_clue_is_ever_certain() -> None:
    assert fuse(
        0.1, {"look": 1.0, "move": None, "sound": None}, WEIGHTS, FLOOR
    ) == pytest.approx(0.98)
    assert fuse(
        0.1, {"look": 0.0, "move": None, "sound": None}, WEIGHTS, FLOOR
    ) == pytest.approx(0.02)


def test_a_zero_weight_ignores_that_clue() -> None:
    weights = {**WEIGHTS, "look": 0.0}
    assert fuse(
        0.1, {"look": 0.95, "move": None, "sound": None}, weights, FLOOR
    ) == pytest.approx(0.1)


def test_clue_values_from_class_scores() -> None:
    assert (
        look_probability({"drone": 0.0, "bird": 0.0}) is None
    )  # unconfirmed, not evidence
    assert look_probability(
        {"drone": 0.4, "bird": 0.1, "airplane": 0.16, "helicopter": 0.12}
    ) == pytest.approx(0.4 / 0.78)
    assert sound_probability(
        {"electric_drone": 0.8, "engine": 0.1, "background": 0.1}
    ) == pytest.approx(0.9)
    assert piston_share(
        {"electric_drone": 0.2, "engine": 0.6, "background": 0.2}
    ) == pytest.approx(0.75)


@pytest.fixture
def classifier(site: SiteConfig) -> Classifier:
    return Classifier(
        site.classify,
        site.tracker.gate_sigmas,
        {s.id: s.position_enu_m for s in site.stations},
        {p.id: p.position_enu_m for p in site.pickets},
        1500.0,
        site.picket_settings.bearing_error_deg,
    )


def track(
    track_id: str,
    at,
    t: float,
    status: str = "confirmed",
    n: int = 3,
    velocity=(0.0, 0.0, 0.0),
) -> Track:
    cov = tuple(tuple(4.0 if i == j else 0.0 for j in range(6)) for i in range(6))
    return Track(
        track_id=track_id,
        t=t,
        position_enu_m=tuple(float(v) for v in at),
        velocity_mps=tuple(float(v) for v in velocity),
        covariance=cov,
        n_stations=n,
        status=status,
    )


def looking_at(
    site: SiteConfig,
    at,
    t: float,
    sensor: str,
    class_probs,
    station_index: int = 0,
    frame: str | None = None,
) -> BearingDetection:
    station = site.stations[station_index]
    azimuth, elevation, _ = bearing_to(station.position_enu_m, at)
    return BearingDetection(
        station_id=station.id,
        sensor=sensor,
        t=t,
        azimuth_deg=azimuth,
        elevation_deg=elevation,
        sigma_deg=site.sensors.get(sensor, site.sensors["rgb"]).sigma_deg,
        class_probs=class_probs,
        snapshot_ref=frame,
    )


def by_id(classified):
    return {c.track.track_id: c.track_class for c in classified}


def test_a_look_goes_to_the_track_it_points_at(
    classifier: Classifier, site: SiteConfig
) -> None:
    look = looking_at(site, TARGET, 0.0, "rgb", {"drone": 0.6, "bird": 0.2})
    out = by_id(
        classifier.update(
            0.0, [track("trk-1", TARGET, 0.0), track("trk-2", OTHER, 0.0)], [look]
        )
    )
    assert out["trk-1"].evidence.look == pytest.approx(0.75)
    assert out["trk-2"].evidence.look is None


def test_an_unconfirmed_look_is_not_evidence(
    classifier: Classifier, site: SiteConfig
) -> None:
    look = looking_at(site, TARGET, 0.0, "rgb", {"drone": 0.0, "bird": 0.0})
    out = by_id(classifier.update(0.0, [track("trk-1", TARGET, 0.0)], [look]))
    assert out["trk-1"].evidence.look is None
    assert out["trk-1"].p_drone == pytest.approx(site.classify.prior)


def test_an_acoustic_bearing_gives_sound_and_engine_type(
    classifier: Classifier, site: SiteConfig
) -> None:
    heard = looking_at(
        site,
        TARGET,
        0.0,
        "acoustic",
        {"electric_drone": 0.2, "engine": 0.6, "background": 0.2},
    )
    fast = (40.0, 0.0, 0.0)
    out = by_id(
        classifier.update(0.0, [track("trk-1", TARGET, 0.0, velocity=fast)], [heard])
    )
    assert out["trk-1"].evidence.sound == pytest.approx(0.8)
    assert out["trk-1"].p_attack_drone == pytest.approx(out["trk-1"].p_drone * 0.75)


def test_a_slow_target_is_never_an_attack_drone(
    classifier: Classifier, site: SiteConfig
) -> None:
    heard = looking_at(
        site,
        TARGET,
        0.0,
        "acoustic",
        {"electric_drone": 0.0, "engine": 1.0, "background": 0.0},
    )
    out = by_id(
        classifier.update(
            0.0, [track("trk-1", TARGET, 0.0, velocity=(10.0, 0.0, 0.0))], [heard]
        )
    )
    assert out["trk-1"].p_attack_drone == 0.0


def picket_alert(site: SiteConfig, at, picket_index: int, t: float) -> PicketAlert:
    picket = site.pickets[picket_index]
    azimuth, _, _ = bearing_to(picket.position_enu_m, at)
    return PicketAlert(
        picket_id=picket.id,
        t=t,
        bearing_deg=azimuth,
        loudness=0.5,
        engine_type_probs={"piston": 0.8, "electric": 0.2},
    )


def test_a_picket_engine_counts_only_for_tracks_in_its_wedge_and_reach(
    classifier: Classifier, site: SiteConfig
) -> None:
    near_pk4 = (1500.0, -1500.0, 80.0)  # about 880 m from pk4, inside its reach
    classifier.heard(picket_alert(site, near_pk4, 3, 0.0))
    tracks = [
        track("trk-1", near_pk4, 0.0),
        track("trk-2", (-1500.0, 1500.0, 80.0), 0.0),
    ]
    out = by_id(classifier.update(0.0, tracks, []))
    assert out["trk-1"].evidence.sound == site.classify.picket_engine_heard
    assert out["trk-2"].evidence.sound is None


def test_coasting_never_adds_movement_history(classifier: Classifier) -> None:
    """Fresh fixes only: a track that only coasts never gets a move clue."""
    classifier.update(0.0, [track("trk-1", TARGET, 0.0)], [])
    for k in range(1, 30):
        out = by_id(
            classifier.update(k * 0.2, [track("trk-1", TARGET, k * 0.2, n=0)], [])
        )
    assert out["trk-1"].evidence.move is None


def test_coasting_never_counts_towards_the_velocity_for_time_to_impact(
    classifier: Classifier,
) -> None:
    """2.8 s of fresh fixes, then 2 s of coasting: still short of 3 s of fresh history."""
    for k in range(25):
        at = (300.0 + 10.0 * k, 900.0, 80.0)
        (out,) = classifier.update(
            k * 0.2, [track("trk-1", at, k * 0.2, n=3 if k < 15 else 0)], []
        )
    assert out.velocity is None


def test_coasting_predictions_never_enter_the_fit(classifier: Classifier) -> None:
    """Fresh fixes on a 50 m/s line, with a coasting stretch placed 200 m off it."""
    for k in range(40):
        fresh = not 15 <= k < 26
        at = (300.0 + 10.0 * k, 900.0 if fresh else 1100.0, 80.0)
        (out,) = classifier.update(
            k * 0.2, [track("trk-1", at, k * 0.2, n=3 if fresh else 0)], []
        )
    assert list(out.velocity) == pytest.approx([50.0, 0.0, 0.0])


def test_fresh_hovering_fixes_give_a_drone_like_move_clue(
    classifier: Classifier, site: SiteConfig
) -> None:
    for k in range(20):
        out = by_id(classifier.update(k * 0.2, [track("trk-1", TARGET, k * 0.2)], []))
    assert out["trk-1"].evidence.move == site.classify.move.drone_like


def test_zoom_looks_replace_wide_looks_after_enough_watching(
    classifier: Classifier, site: SiteConfig
) -> None:
    wide = looking_at(site, TARGET, 0.0, "rgb", {"drone": 0.2, "bird": 0.8})
    classifier.update(0.0, [track("trk-1", TARGET, 0.0)], [wide])
    for k in range(1, 10):
        t = k * 0.2
        zoom = looking_at(site, TARGET, t, "zoom", {"drone": 0.9, "bird": 0.1})
        out = by_id(classifier.update(t, [track("trk-1", TARGET, t)], [zoom]))
        expected = 0.9 if t - 0.2 >= site.classify.zoom_look_after_s else 0.2
        assert out["trk-1"].evidence.look == pytest.approx(expected)


def test_a_lost_track_forgets_its_evidence(
    classifier: Classifier, site: SiteConfig
) -> None:
    look = looking_at(site, TARGET, 0.0, "rgb", {"drone": 0.6, "bird": 0.2})
    classifier.update(0.0, [track("trk-1", TARGET, 0.0)], [look])
    assert (
        classifier.update(0.2, [track("trk-1", TARGET, 0.2, status="lost", n=0)], [])
        == []
    )
    out = by_id(classifier.update(0.4, [track("trk-1", TARGET, 0.4)], []))
    assert out["trk-1"].evidence.look is None


WIDE, ZOOMED = {"drone": 0.2, "bird": 0.8}, {"drone": 0.9, "bird": 0.1}


@pytest.mark.parametrize(
    ("zoom_frame", "look"),
    [("f:7", 0.2), ("g:3", 0.9)],
    ids=["same frame as a wide look", "another frame"],
)
def test_a_zoom_look_on_a_frame_already_seen_wide_is_not_counted(
    classifier: Classifier, site: SiteConfig, zoom_frame: str, look: float
) -> None:
    wide = looking_at(site, TARGET, 0.0, "rgb", WIDE, frame="f:7")
    classifier.update(0.0, [track("trk-1", TARGET, 0.0)], [wide])
    for k in range(1, 10):
        zoom = looking_at(site, TARGET, k * 0.2, "zoom", ZOOMED, frame=zoom_frame)
        out = by_id(
            classifier.update(k * 0.2, [track("trk-1", TARGET, k * 0.2)], [zoom])
        )
    assert out["trk-1"].evidence.look == pytest.approx(look)


def test_wide_frames_from_any_station_count_before_zoom_in_the_same_batch(
    classifier: Classifier, site: SiteConfig
) -> None:
    """st1's zoom and st2's wide camera show the same frame at once: not two looks."""
    zoom = looking_at(site, TARGET, 0.0, "zoom", ZOOMED, frame="f:7")
    wide = looking_at(site, TARGET, 0.0, "rgb", WIDE, station_index=1, frame="f:7")
    classifier.update(0.0, [track("trk-1", TARGET, 0.0)], [zoom, wide])
    for k in range(1, 10):
        zoom = looking_at(site, TARGET, k * 0.2, "zoom", ZOOMED, frame="f:7")
        out = by_id(
            classifier.update(k * 0.2, [track("trk-1", TARGET, k * 0.2)], [zoom])
        )
    assert out["trk-1"].evidence.look == pytest.approx(0.2)


def test_a_track_class_names_the_latest_frame_from_each_camera(
    classifier: Classifier, site: SiteConfig
) -> None:
    """What the clip panel and the evidence need, with no association of their own."""
    first = looking_at(site, TARGET, 0.0, "rgb", WIDE, frame="f:7")
    classifier.update(0.0, [track("trk-1", TARGET, 0.0)], [first])
    later = [
        looking_at(site, TARGET, 0.2, "rgb", WIDE, frame="f:8"),
        looking_at(site, TARGET, 0.2, "zoom", ZOOMED, station_index=1, frame="g:3"),
    ]
    (out,) = classifier.update(0.2, [track("trk-1", TARGET, 0.2)], later)
    assert out.track_class.looks == {"st1.rgb": "f:8", "st2.zoom": "g:3"}


def test_a_track_class_names_the_latest_sound_window_from_each_microphone(
    classifier: Classifier, site: SiteConfig
) -> None:
    """The recorded-audio panel and the evidence need the WAV the classifier heard."""
    sound = {"electric_drone": 0.7, "engine": 0.1, "background": 0.2}
    heard = looking_at(site, TARGET, 0.0, "acoustic", sound, frame="a:3")
    unrecorded = looking_at(site, TARGET, 0.0, "acoustic", sound, station_index=1)
    (out,) = classifier.update(0.0, [track("trk-1", TARGET, 0.0)], [heard, unrecorded])
    assert out.track_class.looks == {"st1.acoustic": "a:3"}


def test_a_track_class_keeps_the_microphone_bearing_the_gate_matched_to_it(
    classifier: Classifier, site: SiteConfig
) -> None:
    """The dashboard's "Last heard from" wedge: the matched bearing itself, never a guess."""
    sound = {"electric_drone": 0.7, "engine": 0.1, "background": 0.2}
    heard = looking_at(site, TARGET, 1.0, "acoustic", sound, frame="a:3")
    away = (-5 * TARGET[0], -5 * TARGET[1], TARGET[2])  # the opposite side of the site
    elsewhere = looking_at(site, away, 1.0, "acoustic", sound, station_index=1)
    (out,) = classifier.update(1.0, [track("trk-1", TARGET, 1.0)], [heard, elsewhere])
    assert out.track_class.heard == {
        "st1.acoustic": HeardBearing(
            t=1.0, azimuth_deg=heard.azimuth_deg, sigma_deg=heard.sigma_deg
        )
    }
    assert '"heard"' in out.track_class.model_dump_json()


def test_a_track_class_with_no_microphone_match_leaves_heard_out_of_the_json(
    classifier: Classifier, site: SiteConfig
) -> None:
    """So output without recorded media, and its digests, stay as they were."""
    look = looking_at(site, TARGET, 0.0, "rgb", {"drone": 0.6, "bird": 0.2})
    (out,) = classifier.update(0.0, [track("trk-1", TARGET, 0.0)], [look])
    assert out.track_class.heard == {}
    assert "heard" not in out.track_class.model_dump_json()
