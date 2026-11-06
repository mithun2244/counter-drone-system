"""Ground truth is for the evaluator only. Nothing on the bus may carry or imply it."""

import pytest
from pydantic import BaseModel

from cuas.bus import InProcessBus
from cuas.schemas import BearingDetection, Message, PicketAlert, SensorStatus
from cuas.sim.scenario import load_scenario
from cuas.sim.truth import BearingTruth, PicketTruth, TargetState, TruthLog

ALL_SCENARIOS = ["s1", "s2", "s3", "s4"]
TARGET_TYPES = ["attack_drone", "quadcopter", "friendly_drone", "bird"]
SAMPLE_TRUTH = [
    TruthLog(),
    TargetState(0.0, "quad-1", "quadcopter", (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
    BearingTruth(0.0, "quad-1", "quadcopter", "st1", "rgb", 0.0, 0.0, 1.0, 2.0),
    PicketTruth(
        0.0, 0.0, "quad-1", "quadcopter", "pk1", 0.0, 1.0, 2.0, "electric", "electric"
    ),
]


@pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
async def test_no_message_mentions_a_target_id_or_type(
    record, scenario_id: str
) -> None:
    messages, truth = await record(scenario_id)
    target_ids = {state.target_id for state in truth.states}
    assert target_ids
    for message in messages:
        text = message.model_dump_json()
        for word in (*target_ids, *TARGET_TYPES):
            assert word not in text, f"{word!r} leaked in {text}"


@pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
async def test_only_observation_types_reach_the_bus(record, scenario_id: str) -> None:
    messages, _ = await record(scenario_id)
    assert {type(m) for m in messages} <= {BearingDetection, PicketAlert, SensorStatus}


@pytest.mark.parametrize("item", SAMPLE_TRUTH, ids=lambda item: type(item).__name__)
async def test_the_bus_refuses_truth_records(item: object) -> None:
    assert not isinstance(item, (Message, BaseModel))
    with pytest.raises(TypeError):
        await InProcessBus().publish("station.bearing", item)  # type: ignore[arg-type]


@pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
async def test_bearings_carry_no_labels_until_phase_2(record, scenario_id: str) -> None:
    messages, _ = await record(scenario_id)
    bearings = [m for m in messages if isinstance(m, BearingDetection)]
    assert bearings
    for bearing in bearings:
        assert bearing.class_probs == {}
        assert bearing.snapshot_ref is None


@pytest.mark.parametrize("scenario_id", ["s1", "s3"])
async def test_target_order_leaves_no_trace_in_the_observations(
    record, config_dir, scenario_id: str
) -> None:
    """If the output followed target order, position in a tick would identify the target."""
    scenario = load_scenario(config_dir, scenario_id)
    flipped = scenario.model_copy(update={"targets": tuple(reversed(scenario.targets))})
    assert flipped.targets != scenario.targets
    original, _ = await record(scenario)
    reordered, _ = await record(flipped)
    assert [m.model_dump_json() for m in original] == [
        m.model_dump_json() for m in reordered
    ]


async def test_picket_engine_guess_is_not_a_perfect_label(record) -> None:
    _, truth = await record("s1")
    guesses = [a.guessed_engine_type == a.engine_type for a in truth.picket_alerts]
    assert len(guesses) >= 20
    assert any(guesses)
    assert not all(guesses)
