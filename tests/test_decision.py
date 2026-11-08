"""Phase 4 acceptance on real baseline runs (no recorded media). Truth is used only to score.

The S1 and S3 gate seeds were declared in docs/memory.md before any run, and the decision rule
was frozen at commit 2ded003 before they ran. Seed 7 was withdrawn after a smoke test saw it;
221 (S1) and 211 (S3) replace it.
"""

import pytest

from cuas.metrics.alert_evaluator import AlertReport, evaluate_alerts

S1_GATE_SEEDS = [None, *range(201, 222)]  # None: the scenario's own seed, 1001
S3_GATE_SEEDS = [None, *range(201, 212)]  # None: 3003
ATTACK_DRONES = {"atk-1", "atk-2", "atk-3"}
WARNING_BELOW_PCT = 80.0
# Phase 3 seeds where S2 and S4 pick a drone up again under a new track ID
REACQUIRED = [
    ("s2", None),
    ("s2", 7),
    *[("s2", s) for s in range(101, 121)],
    ("s4", None),
    ("s4", 7),
    *[("s4", s) for s in range(101, 106)],
]


async def alerts(record_pipeline, scenario_id: str, seed: int | None) -> AlertReport:
    _, _, controlled, truth = await record_pipeline(scenario_id, seed=seed)
    return evaluate_alerts(truth, controlled)


@pytest.mark.parametrize("seed", S1_GATE_SEEDS, ids=str)
async def test_s1_three_red_alerts_in_order_of_arrival(record_pipeline, seed) -> None:
    report = await alerts(record_pipeline, "s1", seed)
    assert report.alerts_per_target == {"atk-1": 1, "atk-2": 1, "atk-3": 1}
    assert set(report.alert_owner.values()) == ATTACK_DRONES
    assert set(report.first_red) == ATTACK_DRONES
    assert report.wrong_alarms == 0, report.wrong_alarm_tracks
    assert report.red_batches > 0
    assert report.out_of_order_batches == 0


@pytest.mark.parametrize("seed", S3_GATE_SEEDS, ids=str)
async def test_s3_birds_stay_below_amber_and_the_quadcopter_reaches_red(
    record_pipeline, seed
) -> None:
    report = await alerts(record_pipeline, "s3", seed)
    assert report.wrong_alarms == 0, report.wrong_alarm_tracks
    assert "quad-1" in report.first_red


async def test_s4_warns_of_coverage_below_80_percent_and_s2_does_not(
    record_pipeline,
) -> None:
    dusty = (await alerts(record_pipeline, "s4", None)).coverage
    clear = (await alerts(record_pipeline, "s2", None)).coverage
    assert min(pct for _, pct, _ in dusty) < WARNING_BELOW_PCT
    assert all(warning for _, pct, warning in dusty if pct < WARNING_BELOW_PCT)
    assert min(pct for _, pct, _ in clear) >= WARNING_BELOW_PCT
    assert not any(warning for _, _, warning in clear)


@pytest.mark.parametrize("scenario_id", ["s1", "s2", "s3", "s4"])
async def test_a_prediction_never_raises_an_alert(record_pipeline, scenario_id) -> None:
    assert (await alerts(record_pipeline, scenario_id, None)).stale_rises == 0


@pytest.mark.parametrize(("scenario_id", "seed"), REACQUIRED, ids=str)
async def test_a_drone_picked_up_again_raises_one_alert(
    record_pipeline, scenario_id, seed
) -> None:
    report = await alerts(record_pipeline, scenario_id, seed)
    assert report.alerts_per_target["quad-1"] == 1
