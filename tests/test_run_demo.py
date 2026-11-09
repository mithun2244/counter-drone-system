import re
import subprocess
import sys
from pathlib import Path

import pytest

RUN_DEMO = Path(__file__).resolve().parents[1] / "scripts" / "run_demo.py"
TARGET_WORDS = re.compile(
    r"atk-\d|quad-\d|flock-\d|attack|quadcopter|bird", re.IGNORECASE
)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUN_DEMO), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def run_fast(scenario: str, *args: str) -> str:
    result = run("--scenario", scenario, "--fast", *args)
    assert result.returncode == 0, result.stderr
    return result.stdout


def digest(output: str) -> str:
    return next(line for line in output.splitlines() if line.startswith("digest: "))


def test_no_arguments_only_reports_the_site() -> None:
    output = run().stdout
    assert "hello" in output
    assert "3 stations, 8 pickets, 3 zones" in output
    assert "bearing" not in output


def test_s1_prints_bearings_from_three_stations_and_picket_alerts() -> None:
    output = run_fast("s1", "--seed", "7")
    for needle in ("bearing st1", "bearing st2", "bearing st3", " picket pk"):
        assert needle in output
    assert "from 3 stations (st1, st2, st3)" in output
    assert "seed: 7" in output


@pytest.mark.parametrize("scenario", ["s1", "s2", "s3", "s4"])
def test_only_evaluator_lines_name_targets(scenario: str) -> None:
    output = run_fast(scenario)
    evaluator = [line for line in output.splitlines() if line.startswith("[evaluator]")]
    rest = [line for line in output.splitlines() if not line.startswith("[evaluator]")]
    assert any(TARGET_WORDS.search(line) for line in evaluator)
    assert not [line for line in rest if TARGET_WORDS.search(line)]


def test_evaluator_output_is_labelled_as_a_simulator_result() -> None:
    assert "[evaluator] simulator results" in run_fast("s2")


@pytest.mark.parametrize(
    ("scenario", "shown", "hidden"),
    [
        ("s1", "critical=Processing Unit", "Pitch and Stands"),
        ("s2", "critical=Pitch and Stands", "Processing Unit"),
        ("s4", "critical=Pitch and Stands", "Processing Unit"),
    ],
)
def test_each_scenario_shows_its_own_zone_labels(
    scenario: str, shown: str, hidden: str
) -> None:
    output = run_fast(scenario)
    assert shown in output
    assert hidden not in output


def test_default_seed_is_the_scenarios_own() -> None:
    assert "seed: 2002" in run_fast("s2")


def test_zoom_per_station_defaults_to_one_and_says_zoom_needs_recorded_media() -> None:
    assert "zoom_per_station: 1 (zoom looks need --recorded-media)" in run_fast("s2")


@pytest.mark.parametrize("zoom", ["0", "2"])
def test_zoom_override_is_shown_and_leaves_the_observations_alone(zoom: str) -> None:
    default = run_fast("s2")
    changed = run_fast("s2", "--zoom-per-station", zoom)
    assert f"zoom_per_station: {zoom} " in changed
    assert digest(changed) == digest(default)


@pytest.mark.parametrize(
    "args",
    [
        ("--zoom-per-station", "3"),
        ("--zoom-per-station", "-1"),
        ("--scenario", "s9"),
        ("--scenario", "s2", "--seed", "-1"),
    ],
)
def test_bad_arguments_exit_with_usage_error(args: tuple[str, ...]) -> None:
    assert run(*args).returncode == 2


def test_evidence_needs_a_scenario() -> None:
    result = run("--evidence")
    assert result.returncode == 2 and "--evidence needs --scenario" in result.stderr
