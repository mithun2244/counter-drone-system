"""The same scenario and seed must give the same observations and timestamps, byte for byte."""

import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from cuas.schemas import BearingDetection, Message

ALL_SCENARIOS = ["s1", "s2", "s3", "s4", "s5"]
RUN_DEMO = Path(__file__).resolve().parents[2] / "scripts" / "run_demo.py"


def lines(messages: list[Message]) -> list[str]:
    """JSON floats round-trip exactly, so comparing these compares timestamps too."""
    return [f"{type(m).__name__} {m.model_dump_json()}" for m in messages]


@pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
async def test_same_seed_same_sequence(record, scenario_id: str) -> None:
    first, _ = await record(scenario_id, seed=7)
    second, _ = await record(scenario_id, seed=7)
    assert first  # an empty run must not pass
    assert lines(first) == lines(second)


def run_cli(hash_seed: str) -> bytes:
    command = [
        sys.executable,
        str(RUN_DEMO),
        "--scenario",
        "s1",
        "--fast",
        "--seed",
        "7",
    ]
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}
    result = subprocess.run(command, env=env, capture_output=True, check=True)
    return result.stdout


def test_same_seed_is_byte_identical_across_processes() -> None:
    """Separate processes salt ``hash()`` differently, which a single process can never show."""
    first, second = run_cli("1"), run_cli("2")
    assert b"bearing st1" in first
    assert first == second


@pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
async def test_timestamps_never_decrease_and_sit_exactly_on_ticks(
    record, site, scenario_id: str
) -> None:
    messages, _ = await record(scenario_id, seed=7)
    times = [message.t for message in messages]
    tick_s = site.simulation.tick_s
    assert times == sorted(times)
    assert all(round(t / tick_s) * tick_s == t for t in times)


@pytest.mark.parametrize("scenario_id", ALL_SCENARIOS)
async def test_a_different_seed_changes_the_sequence(record, scenario_id: str) -> None:
    first, _ = await record(scenario_id, seed=7)
    second, _ = await record(scenario_id, seed=8)
    assert lines(first) != lines(second)


async def test_pace_does_not_change_the_sequence(record) -> None:
    fast, _ = await record("s4", seed=7)
    paced, _ = await record(
        "s4", seed=7, pace=400.0
    )  # 120 simulated seconds in about 0.3 s
    assert lines(fast) == lines(paced)


@pytest.mark.parametrize("zoom", [0, 2])
async def test_zoom_setting_does_not_disturb_wide_sensor_observations(
    record, zoom: int
) -> None:
    """Phase 4's paired S3 comparison relies on this: only the zoom count may differ."""
    default, _ = await record("s3", seed=7)
    changed, _ = await record("s3", seed=7, zoom=zoom)
    assert lines(default) == lines(changed)


async def test_dust_only_removes_detections(record) -> None:
    """S4 is S2 with shorter range: same noise, so its bearings are a subset of S2's."""
    clear, _ = await record("s2", seed=2002)
    dusty, _ = await record("s4", seed=2002)

    def bearings(messages: list[Message]) -> Counter[str]:
        return Counter(
            m.model_dump_json() for m in messages if isinstance(m, BearingDetection)
        )

    clear_bearings, dusty_bearings = bearings(clear), bearings(dusty)
    assert dusty_bearings  # the storm reduces detections, it does not end them
    assert sum(dusty_bearings.values()) < sum(clear_bearings.values())
    assert not dusty_bearings - clear_bearings
