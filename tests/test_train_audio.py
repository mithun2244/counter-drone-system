"""Audio training must never read the test split, even as background noise."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "train_audio.py"


def clip(name: str, label: str, split: str) -> SimpleNamespace:
    return SimpleNamespace(id=name, label=label, split=split)


CLIPS = [
    clip("noise_train", "background", "train"),
    clip("noise_val", "background", "val"),
    clip("noise_test", "background", "test"),
    clip("drone_train", "electric_drone", "train"),
    clip("drone_val", "electric_drone", "val"),
    clip("drone_test", "electric_drone", "test"),
]


def split_clips() -> tuple[list, list, list]:
    spec = importlib.util.spec_from_file_location("train_audio", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.clips_for_training(CLIPS)


def test_noise_comes_only_from_training_clips() -> None:
    _, _, noise = split_clips()
    assert [c.id for c in noise] == ["noise_train"]


def test_no_test_clip_is_read() -> None:
    train, val, noise = split_clips()
    assert not [c.id for c in [*train, *val, *noise] if c.split == "test"]
    assert {c.id for c in train} == {"noise_train", "drone_train"}
    assert {c.id for c in val} == {"noise_val", "drone_val"}
