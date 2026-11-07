"""A long training run must survive being killed. A tiny model stands in for the detector."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
import torch

from cuas.config import TrainingSettings

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "train_detector.py"
CLASSES = ("drone",)
FRAMES = 6
BATCH = 2
EPOCHS = 3
BATCHES_PER_EPOCH = FRAMES // BATCH
SETTINGS = TrainingSettings(
    seed=1,
    batch_size=BATCH,
    learning_rate=0.1,
    weight_decay=0.0,
    epochs=EPOCHS,
    max_minutes=60,
    freeze_backbone=False,
    train_frames_per_clip=1,
    val_frames_per_clip=1,
)


class TinyModel(torch.nn.Module):
    """Its gradient depends on frame order and torch's random state, and it can die on cue."""

    def __init__(self, die_on_call: int | None = None) -> None:
        super().__init__()
        self.weight = torch.nn.Parameter(torch.ones(1))
        self.calls = 0
        self.die_on_call = die_on_call

    def forward(self, images: list[torch.Tensor], targets: list) -> dict:
        self.calls += 1
        if self.calls == self.die_on_call:
            raise KeyboardInterrupt
        brightness = torch.stack([image.mean() for image in images]).mean()
        noise = torch.rand(1)
        return {"loss": ((self.weight * (brightness + noise) - 1) ** 2).sum()}


@pytest.fixture
def module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location("train_detector", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    # Dataclasses look their module up by name while the script runs.
    monkeypatch.setitem(sys.modules, "train_detector", loaded)
    spec.loader.exec_module(loaded)
    monkeypatch.setattr(loaded, "FRAME_CACHE", tmp_path)
    return loaded


@pytest.fixture
def samples(module: ModuleType, tmp_path: Path) -> list:
    clip = SimpleNamespace(id="c")
    for index in range(FRAMES):
        frame = np.full((8, 8, 3), index * 40, dtype=np.uint8)
        np.save(tmp_path / f"c_{index:04d}.npy", frame)
    return [module.Sample(clip, index, ()) for index in range(FRAMES)]


def checkpoint_at(module: ModuleType, tmp_path: Path, run: str = "run"):
    return module.Checkpoint(tmp_path / "look.checkpoint.pt", run)


def unbroken_weight(module: ModuleType, samples: list) -> torch.Tensor:
    torch.manual_seed(SETTINGS.seed)
    model = TinyModel()
    module.train(model, samples, CLASSES, SETTINGS)
    return model.weight.detach().clone()


def kill_during_epoch(
    module: ModuleType, samples: list, checkpoint, epoch: int
) -> None:
    torch.manual_seed(SETTINGS.seed)
    model = TinyModel(die_on_call=(epoch - 1) * BATCHES_PER_EPOCH + 2)
    with pytest.raises(KeyboardInterrupt):
        module.train(model, samples, CLASSES, SETTINGS, None, checkpoint)


def test_a_killed_run_resumes_to_the_same_weights(
    module: ModuleType, samples: list, tmp_path: Path
) -> None:
    expected = unbroken_weight(module, samples)
    checkpoint = checkpoint_at(module, tmp_path)
    kill_during_epoch(module, samples, checkpoint, epoch=2)
    torch.manual_seed(999)  # the saved random state has to win over this one
    model = TinyModel()
    result = module.train(model, samples, CLASSES, SETTINGS, None, checkpoint)
    assert model.weight.detach().equal(expected)
    assert result["epochs_completed"] == EPOCHS
    assert result["batches"] == EPOCHS * BATCHES_PER_EPOCH
    assert (
        model.calls == 2 * BATCHES_PER_EPOCH
    )  # the finished first epoch is not redone


def test_a_run_killed_after_its_last_epoch_trains_no_further(
    module: ModuleType, samples: list, tmp_path: Path
) -> None:
    checkpoint = checkpoint_at(module, tmp_path)
    torch.manual_seed(SETTINGS.seed)
    finished = TinyModel()
    module.train(finished, samples, CLASSES, SETTINGS, None, checkpoint)
    model = TinyModel()
    result = module.train(model, samples, CLASSES, SETTINGS, None, checkpoint)
    assert model.calls == 0
    assert model.weight.detach().equal(finished.weight.detach())
    assert result["epochs_completed"] == EPOCHS


def test_a_checkpoint_from_other_settings_is_refused(
    module: ModuleType, samples: list, tmp_path: Path
) -> None:
    kill_during_epoch(module, samples, checkpoint_at(module, tmp_path), epoch=2)
    other = checkpoint_at(module, tmp_path, run="other settings")
    with pytest.raises(SystemExit, match="other settings"):
        module.train(TinyModel(), samples, CLASSES, SETTINGS, None, other)


def test_a_kill_during_the_write_keeps_the_last_good_checkpoint(
    module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = checkpoint_at(module, tmp_path)
    checkpoint.save({"epochs": 1})

    def die_halfway(_: object, path: Path) -> None:
        path.write_bytes(b"half a file")
        raise KeyboardInterrupt

    monkeypatch.setattr(module.torch, "save", die_halfway)
    with pytest.raises(KeyboardInterrupt):
        checkpoint.save({"epochs": 2})
    assert checkpoint.load()["epochs"] == 1
