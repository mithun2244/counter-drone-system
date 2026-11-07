"""Hand-calculated cases for the track evaluator."""

import pytest

from cuas.metrics.track_evaluator import FALSE_TRACK_M, evaluate_tracks
from cuas.schemas import Track
from cuas.sim.truth import TargetState, TruthLog

A_AT = (0.0, 0.0, 100.0)
B_AT = (1000.0, 0.0, 100.0)


def flying(
    target_id: str, at, times, target_type: str = "attack_drone"
) -> list[TargetState]:
    return [TargetState(t, target_id, target_type, at, (0.0, 0.0, 0.0)) for t in times]


def track(track_id: str, t: float, at, status: str = "confirmed") -> Track:
    return Track(
        track_id=track_id,
        t=t,
        position_enu_m=tuple(float(v) for v in at),
        velocity_mps=(0.0, 0.0, 0.0),
        covariance=((1.0,),),
        n_stations=3,
        status=status,
    )


def off(at, east_m: float):
    return (at[0] + east_m, at[1], at[2])


def test_error_is_measured_against_the_owner_while_it_flies() -> None:
    truth = TruthLog(states=flying("atk-1", A_AT, [0.0, 1.0, 2.0]))
    tracks = [
        track("trk-1", t, off(A_AT, e)) for t, e in [(0.0, 1.0), (1.0, 2.0), (2.0, 6.0)]
    ]
    tracks.append(track("trk-1", 3.0, off(A_AT, 50.0)))  # after the flight ended
    report = evaluate_tracks(truth, tracks)
    assert (report.median_error_m, report.scored, report.after_flight) == (2.0, 3, 1)
    assert report.p95_error_m == pytest.approx(5.6)  # 2 + 0.9 * (6 - 2)
    assert report.worst_target == ("atk-1", 2.0)


def test_tentative_and_lost_messages_are_never_scored() -> None:
    truth = TruthLog(states=flying("atk-1", A_AT, [0.0, 1.0, 2.0]))
    tracks = [
        track("trk-1", 0.0, off(A_AT, 900.0), "tentative"),
        track("trk-1", 1.0, off(A_AT, 1.0)),
        track("trk-1", 2.0, off(A_AT, 900.0), "lost"),
    ]
    report = evaluate_tracks(truth, tracks)
    assert (report.confirmed, report.scored, report.median_error_m) == (1, 1, 1.0)


def test_a_track_far_from_every_target_is_false() -> None:
    truth = TruthLog(states=flying("atk-1", A_AT, [0.0, 1.0]))
    tracks = [track("trk-1", t, off(A_AT, FALSE_TRACK_M + 1.0)) for t in (0.0, 1.0)]
    report = evaluate_tracks(truth, tracks)
    assert (report.confirmed, report.false_tracks) == (1, 1)
    assert report.tracks_per_target == {"atk-1": 0}
    assert report.drones_tracked == (0, 1)


def test_the_owner_is_the_target_nearest_most_often() -> None:
    truth = TruthLog(
        states=[
            *flying("atk-1", A_AT, [0.0, 1.0, 2.0]),
            *flying("atk-2", B_AT, [0.0, 1.0, 2.0]),
        ]
    )
    tracks = [
        track("trk-1", 0.0, off(A_AT, 5.0)),
        track("trk-1", 1.0, off(A_AT, 5.0)),
        track("trk-1", 2.0, off(B_AT, -5.0)),  # wanders over to the other target once
    ]
    report = evaluate_tracks(truth, tracks)
    assert report.tracks_per_target == {"atk-1": 1, "atk-2": 0}
    assert report.median_error_m == 5.0  # the third message is 995 m from its owner
    assert report.scored == 3


def test_two_tracks_on_one_target_at_once_are_overlapping_duplicates() -> None:
    truth = TruthLog(states=flying("atk-1", A_AT, [0.0, 1.0, 2.0]))
    tracks = [track(i, t, A_AT) for i in ("trk-1", "trk-2") for t in (0.0, 1.0)]
    report = evaluate_tracks(truth, tracks)
    assert (report.overlapping_duplicates, report.sequential_duplicates) == (1, 0)
    assert report.tracks_per_target == {"atk-1": 2}


def test_a_target_picked_up_again_later_is_a_sequential_duplicate() -> None:
    truth = TruthLog(states=flying("quad-1", A_AT, [0.0, 1.0, 2.0, 3.0], "quadcopter"))
    tracks = [
        track("trk-1", 0.0, A_AT),
        track("trk-1", 1.0, A_AT),
        track("trk-2", 3.0, A_AT),
    ]
    report = evaluate_tracks(truth, tracks)
    assert (report.overlapping_duplicates, report.sequential_duplicates) == (0, 1)


def test_first_confirmation_time_and_distance_from_the_site_centre() -> None:
    truth = TruthLog(states=flying("atk-1", (300.0, -400.0, 80.0), [4.0, 5.0]))
    report = evaluate_tracks(truth, [track("trk-1", 5.0, (300.0, -400.0, 80.0))])
    assert report.first_confirmed == {"atk-1": (5.0, 500.0)}


def test_drones_and_birds_are_counted_apart() -> None:
    truth = TruthLog(
        states=[
            *flying("quad-1", A_AT, [0.0], "quadcopter"),
            *flying("flock-1-01", B_AT, [0.0], "bird"),
            *flying("flock-1-02", (0.0, 2000.0, 80.0), [0.0], "bird"),
        ]
    )
    report = evaluate_tracks(
        truth, [track("trk-1", 0.0, A_AT), track("trk-2", 0.0, B_AT)]
    )
    assert report.drones_tracked == (1, 1)
    assert report.birds_tracked == (1, 2)


def test_no_confirmed_tracks_gives_no_error_rather_than_zero() -> None:
    report = evaluate_tracks(TruthLog(states=flying("atk-1", A_AT, [0.0])), [])
    assert (report.median_error_m, report.p95_error_m, report.worst_target) == (
        None,
        None,
        None,
    )
    assert report.confirmed == 0
