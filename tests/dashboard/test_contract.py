"""The dashboard contract: schema in step with the models, samples valid, current and truth-free."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from cuas.dashboard.contract import (
    CONTRACT_VERSION,
    DECIMALS,
    RunControl,
    ServerMessage,
    schema_text,
)
from cuas.sim.scenario import available_scenarios, load_scenario

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "docs" / "dashboard_contract.schema.json"
SAMPLES = ROOT / "docs" / "samples"
RECORDED = {
    "s1_seed1001.jsonl": "s1",
    "s4_seed2002.jsonl": "s4",
    "s5_seed5005.jsonl": "s5",
}
MESSAGES = TypeAdapter(ServerMessage)
TARGET_TYPES = {"attack_drone", "quadcopter", "friendly_drone", "bird"}


def sample_lines(name: str) -> list[str]:
    return (SAMPLES / name).read_text(encoding="utf-8").splitlines()


def strings_in(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings_in(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings_in(v)]
    return []


def numbers_in(value: object) -> list[float]:
    if isinstance(value, float):
        return [value]
    if isinstance(value, dict):
        return [n for v in value.values() for n in numbers_in(v)]
    if isinstance(value, list):
        return [n for v in value for n in numbers_in(v)]
    return []


def test_the_committed_schema_matches_the_models() -> None:
    """Regenerate with: uv run python scripts/record_stream.py --schema"""
    assert SCHEMA.read_text(encoding="utf-8") == schema_text()


@pytest.mark.parametrize("name", [*RECORDED, "edge_states.jsonl"])
def test_every_sample_line_is_a_valid_current_message(name: str) -> None:
    for line in sample_lines(name):
        message = MESSAGES.validate_json(line)
        assert message.contract == CONTRACT_VERSION
        assert (
            message.model_dump_json() == line
        )  # nothing lost or added on a round trip


@pytest.mark.parametrize("name", [*RECORDED, "edge_states.jsonl"])
def test_samples_carry_no_ground_truth(name: str) -> None:
    target_ids = {
        target.id
        for scenario_id in available_scenarios(ROOT / "config")
        for target in load_scenario(ROOT / "config", scenario_id).targets
    }
    for line in sample_lines(name):
        for text in strings_in(json.loads(line)):
            assert text not in TARGET_TYPES
            assert not any(target_id in text for target_id in target_ids), text


@pytest.mark.parametrize("name", RECORDED)
def test_numbers_are_sent_at_display_precision(name: str) -> None:
    for line in sample_lines(name)[:40]:
        for number in numbers_in(json.loads(line)):
            assert round(number, DECIMALS) == number


def test_the_edge_states_sample_says_it_is_a_mock() -> None:
    first_run = json.loads(sample_lines("edge_states.jsonl")[1])
    assert first_run["run_id"].startswith("mock-")
    assert first_run["title"].startswith("MOCK")


@pytest.mark.parametrize(("name", "scenario_id"), RECORDED.items())
def test_recorded_samples_are_what_the_code_produces_now(
    name: str, scenario_id: str, tmp_path: Path
) -> None:
    """Regenerate with: uv run python scripts/record_stream.py --scenario <id> --out <file>"""
    out = tmp_path / name
    subprocess.run(
        [
            sys.executable,
            "scripts/record_stream.py",
            "--scenario",
            scenario_id,
            "--out",
            str(out),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    assert out.read_text(encoding="utf-8") == (SAMPLES / name).read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    "body",
    [
        {"action": "speed"},
        {"action": "pause", "speed": 2},
        {"action": "speed", "speed": 3},
    ],
)
def test_run_control_rejects_a_missing_or_stray_speed(body: dict) -> None:
    with pytest.raises(ValueError):
        RunControl.model_validate(body)
