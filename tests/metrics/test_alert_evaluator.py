"""Hand-built cases for the alert evaluator."""

from cuas.metrics.alert_evaluator import FALSE, UNCONFIRMED, evaluate_alerts
from cuas.schemas import ThreatAssessment, Track
from cuas.sim.truth import TargetState, TruthLog

A_AT, B_AT, BIRD_AT = (0.0, 500.0, 80.0), (0.0, 900.0, 80.0), (600.0, 0.0, 60.0)


def flying(target_id, at, until, target_type="attack_drone") -> list[TargetState]:
    return [
        TargetState(k * 1.0, target_id, target_type, at, (0.0, 0.0, 0.0))
        for k in range(until + 1)
    ]


def track(track_id, t, at, status="confirmed", n=3) -> Track:
    cov = tuple(tuple(1.0 if i == j else 0.0 for j in range(6)) for i in range(6))
    return Track(
        track_id=track_id,
        t=t,
        position_enu_m=at,
        velocity_mps=(0.0, 0.0, 0.0),
        covariance=cov,
        n_stations=n,
        status=status,
    )


def threat(track_id, t, level, alert_id=None) -> ThreatAssessment:
    return ThreatAssessment(
        track_id=track_id,
        t=t,
        score={"red": 0.9, "amber": 0.4, "info": 0.1}[level],
        level=level,
        zone="critical",
        time_to_impact_s=None,
        reasons=(),
        alert_id=alert_id,
    )


TRUTH = TruthLog(
    states=[
        *flying("atk-1", A_AT, 5),
        *flying("atk-2", B_AT, 8),
        *flying("flock-1-01", BIRD_AT, 8, "bird"),
    ]
)


def test_an_alert_continued_by_a_new_track_counts_once() -> None:
    messages = [
        track("trk-1", 0.0, A_AT),
        threat("trk-1", 0.0, "red", "alert-1"),
        track("trk-1", 1.0, A_AT),
        threat("trk-1", 1.0, "red", "alert-1"),
        track("trk-2", 2.0, A_AT),
        threat("trk-2", 2.0, "red", "alert-1"),
    ]
    report = evaluate_alerts(TRUTH, messages)
    assert report.alert_owner == {"alert-1": "atk-1"}
    assert report.alerts_per_target == {"atk-1": 1, "atk-2": 0, "flock-1-01": 0}


def test_amber_or_red_on_anything_but_a_drone_is_a_wrong_alarm() -> None:
    far = (3000.0, 3000.0, 80.0)
    messages = [
        track("trk-1", 0.0, BIRD_AT),
        threat("trk-1", 0.0, "amber", "alert-1"),
        track("trk-2", 0.0, far),
        track("trk-2", 1.0, far),
        threat("trk-2", 1.0, "red", "alert-2"),
        track("trk-3", 1.0, A_AT, status="tentative"),
        threat("trk-3", 1.0, "red", "alert-3"),
        track("trk-4", 1.0, A_AT),
        threat("trk-4", 1.0, "red", "alert-4"),
    ]
    report = evaluate_alerts(TRUTH, messages)
    assert report.wrong_alarms == 3
    assert report.wrong_alarm_tracks == {
        "trk-1": "flock-1-01",
        "trk-2": FALSE,
        "trk-3": UNCONFIRMED,
    }


def test_reds_listed_out_of_true_arrival_order_are_counted() -> None:
    """atk-1 arrives at 5 s and atk-2 at 8 s, so atk-1 must be listed first."""
    messages = [
        track("trk-1", 1.0, A_AT),
        track("trk-2", 1.0, B_AT),
        threat("trk-1", 1.0, "red", "alert-1"),
        threat("trk-2", 1.0, "red", "alert-2"),
        track("trk-1", 2.0, A_AT),
        track("trk-2", 2.0, B_AT),
        threat("trk-2", 2.0, "red", "alert-2"),
        threat("trk-1", 2.0, "red", "alert-1"),
    ]
    report = evaluate_alerts(TRUTH, messages)
    assert (report.red_batches, report.out_of_order_batches) == (2, 1)


def test_rises_and_new_alerts_without_a_fresh_fix_are_stale() -> None:
    messages = [
        track("trk-1", 0.0, A_AT),
        threat("trk-1", 0.0, "info"),
        track("trk-1", 1.0, A_AT, n=0),
        threat("trk-1", 1.0, "amber", "alert-1"),  # stale
        track("trk-1", 2.0, A_AT, n=0),
        threat("trk-1", 2.0, "red", "alert-1"),  # stale
        track("trk-2", 0.0, B_AT),
        threat("trk-2", 0.0, "amber", "alert-2"),  # fresh
        track("trk-2", 1.0, B_AT),
        threat("trk-2", 1.0, "red", "alert-2"),  # fresh
    ]
    assert evaluate_alerts(TRUTH, messages).stale_rises == 2


def test_first_red_is_timed_from_the_start_of_its_track() -> None:
    messages = [
        track("trk-1", 1.0, A_AT),
        threat("trk-1", 1.0, "amber", "alert-1"),
        track("trk-1", 4.0, A_AT),
        threat("trk-1", 4.0, "red", "alert-1"),
    ]
    assert evaluate_alerts(TRUTH, messages).first_red == {"atk-1": (4.0, 3.0)}
