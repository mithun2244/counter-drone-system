"""Phase 4 acceptance on real baseline runs (no recorded media). Truth is used only to score.

Gate seeds are declared in docs/memory.md before any run, and the rule is frozen before they run.
The first set (201 on) gated the rule frozen at commit 2ded003. Seed 7 was withdrawn after a
smoke test saw it; 221 (S1) and 211 (S3) replaced it. S1 seed 216 failed that gate, so the
first set stays as regression cases, and the 301 sets gate the 3 s time-to-impact change.
"""

import pytest

from cuas.metrics.alert_evaluator import AlertReport, evaluate_alerts
from cuas.schemas import ThreatAssessment

S1_GATE_SEEDS = [None, *range(201, 222), *range(301, 323)]  # None: its own seed, 1001
S3_GATE_SEEDS = [None, *range(201, 212), *range(301, 313)]  # None: 3003
S4_GATE_SEEDS = list(range(301, 313))  # through every test that runs S4
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
    *[("s4", s) for s in S4_GATE_SEEDS],
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


@pytest.mark.parametrize("seed", [None, *S4_GATE_SEEDS], ids=str)
async def test_s4_warns_of_coverage_below_80_percent_and_s2_does_not(
    record_pipeline, seed
) -> None:
    dusty = (await alerts(record_pipeline, "s4", seed)).coverage
    clear = (await alerts(record_pipeline, "s2", seed)).coverage
    assert min(pct for _, pct, _ in dusty) < WARNING_BELOW_PCT
    assert all(warning for _, pct, warning in dusty if pct < WARNING_BELOW_PCT)
    assert min(pct for _, pct, _ in clear) >= WARNING_BELOW_PCT
    assert not any(warning for _, _, warning in clear)


@pytest.mark.parametrize(
    ("scenario_id", "seed"),
    [("s1", None), ("s2", None), ("s3", None), ("s4", None)]
    + [("s4", s) for s in S4_GATE_SEEDS],
    ids=str,
)
async def test_a_prediction_never_raises_an_alert(
    record_pipeline, scenario_id, seed
) -> None:
    assert (await alerts(record_pipeline, scenario_id, seed)).stale_rises == 0


@pytest.mark.parametrize(("scenario_id", "seed"), REACQUIRED, ids=str)
async def test_a_drone_picked_up_again_raises_one_alert(
    record_pipeline, scenario_id, seed
) -> None:
    report = await alerts(record_pipeline, scenario_id, seed)
    assert report.alerts_per_target["quad-1"] == 1


async def test_s4_seed_10_red_alert_holds_through_its_gap(record_pipeline) -> None:
    """Regression: with no fresh fix from 58.2 s to 60.6 s, a 5 s fit window alone held only
    2.8 s at 63.4 s. Time to impact went pending and the red alert dropped to info for one batch,
    1.2 s before the quadcopter entered the critical zone at 64.6 s."""
    _, _, controlled, truth = await record_pipeline("s4", seed=10)
    owner = evaluate_alerts(truth, controlled).alert_owner
    (alert_id,) = [a for a, target in owner.items() if target == "quad-1"]
    levels = {
        a.t: a.level
        for a in controlled
        if isinstance(a, ThreatAssessment) and a.alert_id == alert_id
    }
    assert {level for t, level in levels.items() if 60.6 <= t <= 64.6} == {"red"}
