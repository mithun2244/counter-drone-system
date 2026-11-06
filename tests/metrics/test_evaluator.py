import pytest

from cuas.metrics.evaluator import summarize
from cuas.sim.truth import BearingTruth, PicketTruth, TargetState, TruthLog


def state(t: float, target_id: str = "atk-1") -> TargetState:
    return TargetState(t, target_id, "attack_drone", (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))


def bearing(t: float, station_id: str, target_id: str = "atk-1") -> BearingTruth:
    return BearingTruth(
        t, target_id, "attack_drone", station_id, "rgb", 0.0, 0.0, 100.0, 3000.0
    )


def alert(t: float, target_id: str = "atk-1") -> PicketTruth:
    return PicketTruth(
        t,
        t - 1.0,
        target_id,
        "attack_drone",
        "pk4",
        135.0,
        1000.0,
        1500.0,
        "piston",
        "piston",
    )


def test_summary_has_known_counts_times_and_warning() -> None:
    truth = TruthLog(
        states=[state(0.0), state(100.0)],
        bearings=[bearing(60.0, "st2"), bearing(61.0, "st1"), bearing(62.0, "st2")],
        picket_alerts=[alert(30.0), alert(25.0)],
    )
    summary = summarize(truth)[0]
    assert summary.target_id == "atk-1"
    assert summary.target_type == "attack_drone"
    assert summary.bearings_by_station == {"st1": 1, "st2": 2}
    assert summary.first_bearing_s == 60.0
    assert summary.first_picket_alert_s == 25.0
    assert summary.arrival_s == 100.0
    assert summary.warning_s == 75.0


def test_a_target_nothing_saw_has_no_times() -> None:
    summary = summarize(TruthLog(states=[state(5.0)]))[0]
    assert summary.bearings_by_station == {}
    assert summary.first_bearing_s is None
    assert summary.first_picket_alert_s is None
    assert summary.warning_s is None


def test_summaries_are_per_target_in_id_order() -> None:
    truth = TruthLog(
        states=[state(1.0, "b"), state(1.0, "a")],
        bearings=[bearing(1.0, "st1", "b")],
    )
    summaries = summarize(truth)
    assert [s.target_id for s in summaries] == ["a", "b"]
    assert summaries[0].bearings_by_station == {}
    assert summaries[1].bearings_by_station == {"st1": 1}


def test_an_empty_log_gives_no_summaries() -> None:
    assert summarize(TruthLog()) == []


@pytest.mark.parametrize("seed", [1001, 7])
async def test_s1_warning_meets_the_prd_target_for_every_drone(
    record, seed: int
) -> None:
    """A simulator result, measured by the evaluator: prd.md section 8 asks for at least 45 s."""
    _, truth = await record("s1", seed=seed)
    summaries = summarize(truth)
    assert [s.target_id for s in summaries] == ["atk-1", "atk-2", "atk-3"]
    for summary in summaries:
        assert summary.warning_s is not None
        assert summary.warning_s >= 45.0
