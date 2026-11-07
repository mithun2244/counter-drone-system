"""Alert identity: stale predictions, re-acquisition and separate drones."""

import pytest

from cuas.config import SiteConfig
from cuas.control.alerts import AlertKeeper
from cuas.control.threat import Assessment
from cuas.schemas import Track

RED, AMBER, INFO = ("red", 0.9), ("amber", 0.4), ("info", 0.1)


@pytest.fixture
def keeper(site: SiteConfig) -> AlertKeeper:
    return AlertKeeper(site.alerts)


def track(
    track_id,
    t,
    at=(0.0, 500.0, 80.0),
    status="confirmed",
    n=3,
    velocity=(0.0, -10.0, 0.0),
    sigma=5.0,
) -> Track:
    cov = tuple(tuple(sigma**2 if i == j else 0.0 for j in range(6)) for i in range(6))
    return Track(
        track_id=track_id,
        t=t,
        position_enu_m=tuple(float(v) for v in at),
        velocity_mps=tuple(float(v) for v in velocity),
        covariance=cov,
        n_stations=n,
        status=status,
    )


def raw(track_id, t, level_score) -> Assessment:
    level, score = level_score
    return Assessment(
        track_id, t, score, level, "critical", 20.0, ("fast straight flight",)
    )


def step(keeper, t, *pairs):
    """pairs of (Track, (level, score)); returns {track_id: (level, alert_id, reasons)}."""
    out = keeper.update(
        t,
        [p[0] for p in pairs],
        [raw(p[0].track_id, t, p[1]) for p in pairs if p[0].status != "lost"],
    )
    return {a.track_id: (a.level, a.alert_id, a.reasons) for a in out}


def test_a_tentative_track_never_alerts(keeper: AlertKeeper) -> None:
    assert step(keeper, 0.0, (track("trk-1", 0.0, status="tentative"), RED))["trk-1"][
        :2
    ] == ("info", None)


def test_a_confirmed_fresh_track_raises_one_alert(keeper: AlertKeeper) -> None:
    first = step(keeper, 0.0, (track("trk-1", 0.0), AMBER))["trk-1"]
    later = step(keeper, 0.2, (track("trk-1", 0.2), RED))["trk-1"]
    assert first[:2] == ("amber", "alert-1")
    assert later[:2] == ("red", "alert-1")  # escalation, not a second alert


def test_a_coasting_track_holds_its_level_and_says_so(keeper: AlertKeeper) -> None:
    step(keeper, 0.0, (track("trk-1", 0.0), AMBER))
    coasting = step(keeper, 1.0, (track("trk-1", 1.0, n=0), RED))["trk-1"]
    assert coasting[:2] == ("amber", "alert-1")
    assert "no fresh fix for 1.0 s" in coasting[2]
    fixed_again = step(keeper, 1.2, (track("trk-1", 1.2), RED))["trk-1"]
    assert fixed_again[:2] == ("red", "alert-1")


def test_a_prediction_alone_never_raises_a_new_alert(keeper: AlertKeeper) -> None:
    step(keeper, 0.0, (track("trk-1", 0.0), INFO))
    for k in range(1, 15):
        out = step(keeper, k * 0.2, (track("trk-1", k * 0.2, n=0), RED))["trk-1"]
        assert out[:2] == ("info", None)


def lose(keeper, track_id, t, at, velocity=(0.0, -10.0, 0.0)) -> None:
    step(
        keeper,
        t,
        (
            track(
                track_id, t, at=at, status="lost", n=0, velocity=velocity, sigma=40.0
            ),
            RED,
        ),
    )


def test_a_target_picked_up_again_continues_its_alert(keeper: AlertKeeper) -> None:
    step(keeper, 0.0, (track("trk-1", 0.0), RED))
    lose(keeper, "trk-1", 3.0, at=(0.0, 470.0, 80.0))
    # 2 s later it is found 20 m further on, under a new track ID
    out = step(keeper, 5.0, (track("trk-2", 5.0, at=(0.0, 450.0, 80.0)), RED))["trk-2"]
    assert out[:2] == ("red", "alert-1")


def test_a_new_track_far_from_the_lost_one_raises_its_own_alert(
    keeper: AlertKeeper,
) -> None:
    step(keeper, 0.0, (track("trk-1", 0.0), RED))
    lose(keeper, "trk-1", 3.0, at=(0.0, 470.0, 80.0))
    out = step(keeper, 5.0, (track("trk-2", 5.0, at=(900.0, -400.0, 80.0)), RED))[
        "trk-2"
    ]
    assert out[:2] == ("red", "alert-2")


def test_after_the_window_a_lost_alert_is_not_continued(
    keeper: AlertKeeper, site: SiteConfig
) -> None:
    step(keeper, 0.0, (track("trk-1", 0.0), RED))
    lose(keeper, "trk-1", 3.0, at=(0.0, 470.0, 80.0), velocity=(0.0, 0.0, 0.0))
    later = 3.0 + site.alerts.relink_window_s + 0.2
    out = step(keeper, later, (track("trk-2", later, at=(0.0, 470.0, 80.0)), RED))[
        "trk-2"
    ]
    assert out[1] == "alert-2"


def test_two_drones_flying_together_keep_two_alerts(keeper: AlertKeeper) -> None:
    out = step(
        keeper,
        0.0,
        (track("trk-1", 0.0, at=(0.0, 500.0, 80.0)), RED),
        (track("trk-2", 0.0, at=(50.0, 500.0, 80.0)), RED),
    )
    assert {out["trk-1"][1], out["trk-2"][1]} == {"alert-1", "alert-2"}


def test_one_lost_alert_goes_to_one_new_track_only(keeper: AlertKeeper) -> None:
    step(keeper, 0.0, (track("trk-1", 0.0), RED))
    lose(keeper, "trk-1", 3.0, at=(0.0, 470.0, 80.0))
    out = step(
        keeper,
        5.0,
        (
            track("trk-2", 5.0, at=(0.0, 452.0, 80.0)),
            RED,
        ),  # nearer where it was heading
        (track("trk-3", 5.0, at=(30.0, 440.0, 80.0)), RED),
    )
    assert out["trk-2"][1] == "alert-1"
    assert out["trk-3"][1] == "alert-2"


def test_live_tracks_never_take_each_others_alert(keeper: AlertKeeper) -> None:
    """Only lost tracks can be continued, so a still-live alerted track keeps its own."""
    step(keeper, 0.0, (track("trk-1", 0.0), RED))
    out = step(
        keeper,
        0.2,
        (track("trk-1", 0.2), RED),
        (track("trk-2", 0.2, at=(0.0, 498.0, 80.0)), RED),
    )
    assert out["trk-1"][1] == "alert-1"
    assert out["trk-2"][1] == "alert-2"
