"""Microphone or camera first (scripts/acoustic_lead.py): simulator results, bus messages only."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "acoustic_lead.py"


@pytest.fixture(scope="module")
def lead() -> ModuleType:
    spec = importlib.util.spec_from_file_location("acoustic_lead", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_s5_shows_the_acoustic_warning_before_any_camera_bearing(
    lead: ModuleType,
) -> None:
    """The acoustic-first demo: fog leaves the cameras less range than the microphones."""
    out = lead.measure("s5")
    assert out["microphone_bearing"] <= out["warning_frame"] < out["camera_bearing"]
    assert out["camera_bearing"] < out["confirmed_track"] < out["alert_frame"]
    assert out["lead_warning_s"] > 0


def test_s2_is_camera_first_and_never_shows_the_warning(lead: ModuleType) -> None:
    out = lead.measure("s2")
    assert out["camera_bearing"] < out["microphone_bearing"]
    assert out["warning_frame"] is None


def test_a_scenario_with_several_targets_is_refused(lead: ModuleType) -> None:
    """Without ground truth, bearings cannot be tied to one of several drones."""
    with pytest.raises(SystemExit, match="3 targets"):
        lead.measure("s1")
