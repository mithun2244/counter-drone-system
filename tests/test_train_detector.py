"""A long training run must survive being killed, on the CPU or on an opt-in GPU.

No GPU is needed here. A tiny model stands in for the detector, and the meta device stands in for
a GPU where only the placement of tensors matters.
"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
import torch

from cuas.config import TrainingSettings, load_site
from cuas.hashing import sha256_of
from cuas.media_manifest import MANIFEST_NAME
from cuas.station.detector import build_model, load_trained

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "train_detector.py"
SMALL_SIZE = (
    128  # keeps the full-script tests quick; the real size comes from site.yaml
)
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


def test_a_checkpoint_saved_on_a_gpu_resumes_on_the_cpu(
    module: ModuleType,
    samples: list,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = unbroken_weight(module, samples)
    checkpoint = checkpoint_at(module, tmp_path)
    kill_during_epoch(module, samples, checkpoint, epoch=2)
    state = torch.load(checkpoint.path)
    with monkeypatch.context() as patch:
        patch.setattr(torch.serialization, "location_tag", lambda _: "cuda:0")
        torch.save(state, checkpoint.path)
    model = TinyModel()
    module.train(model, samples, CLASSES, SETTINGS, None, checkpoint)
    assert model.weight.detach().equal(expected)


def test_cpu_needs_no_gpu_and_says_where_it_trains(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert module.resolve_device("cpu") == torch.device("cpu")
    assert "training device: cpu" in capsys.readouterr().out


def test_a_cuda_request_prints_the_real_gpu_name(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda: "Tesla T4")
    assert module.resolve_device("cuda") == torch.device("cuda")
    assert "training device: Tesla T4" in capsys.readouterr().out


def test_a_cuda_request_fails_clearly_instead_of_falling_back(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(SystemExit, match="Not falling back to the CPU"):
        module.resolve_device("cuda")


def test_a_whole_batch_moves_to_the_chosen_device(module: ModuleType) -> None:
    target = {"boxes": torch.zeros(1, 4), "labels": torch.ones(1, dtype=torch.int64)}
    meta = torch.device("meta")  # any device that is not the CPU
    images, targets = module.to_device([torch.zeros(3, 4, 4)], [target], meta)
    assert images[0].device == meta
    assert {value.device for value in targets[0].values()} == {meta}


def test_training_feeds_the_model_on_the_chosen_device(
    module: ModuleType, samples: list
) -> None:
    seen: set[torch.device] = set()

    class SeesDevices(TinyModel):
        def forward(self, images: list[torch.Tensor], targets: list) -> dict:
            seen.update(image.device for image in images)
            seen.update(v.device for target in targets for v in target.values())
            return {"loss": (self.weight**2).sum()}

    module.train(SeesDevices(), samples, CLASSES, SETTINGS, device=torch.device("meta"))
    assert seen == {torch.device("meta")}


def run_main(monkeypatch: pytest.MonkeyPatch, module: ModuleType, *flags: str) -> int:
    monkeypatch.setattr(
        sys, "argv", ["train_detector.py", "--modality", "thermal", *flags]
    )
    return module.main()


@pytest.fixture
def small_run(
    module: ModuleType, samples: list, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> SimpleNamespace:
    """A real SSDLite and the real manifest hash, with a few tiny frames as the dataset."""
    ai = load_site(module.CONFIG_DIR).station_ai
    small = ai.model_copy(
        update={
            "detector": ai.detector.model_copy(update={"input_size": SMALL_SIZE}),
            "training": SETTINGS.model_copy(update={"epochs": 1}),
        }
    )
    clip = SimpleNamespace(
        id="c",
        modality="thermal",
        label="drone",
        group="g",
        distance_bin="medium",
        split="train",
    )
    box = module.Box(1.0, 1.0, 6.0, 6.0, 1.0, "drone")
    frames = [module.Sample(clip, s.index, (box,)) for s in samples]
    held_out = SimpleNamespace(**{**vars(clip), "split": "val"})
    monkeypatch.setattr(
        module, "load_site", lambda _: SimpleNamespace(station_ai=small)
    )
    monkeypatch.setattr(
        module, "load_manifest", lambda _: SimpleNamespace(clips=[clip, held_out])
    )
    monkeypatch.setattr(module, "sample_clip", lambda *_: frames)
    monkeypatch.setattr(module, "build_for_training", lambda s, _: build_model(s))
    monkeypatch.setattr(module, "MODELS_DIR", tmp_path / "models")
    return SimpleNamespace(detector=small.detector, models=tmp_path / "models")


def test_cpu_stays_the_default_and_its_weights_load_in_the_evaluator(
    module: ModuleType, small_run: SimpleNamespace, monkeypatch, capsys
) -> None:
    assert run_main(monkeypatch, module) == 0
    assert "training device: cpu" in capsys.readouterr().out
    record = json.loads((small_run.models / "look_thermal.json").read_text("utf-8"))
    assert record["trained_on"] == "cpu"
    assert record["manifest_sha256"] == sha256_of(module.CONFIG_DIR / MANIFEST_NAME)
    assert not (small_run.models / "look_thermal.checkpoint.pt").exists()
    detector = load_trained(small_run.detector, small_run.models / "look_thermal.pt")
    assert isinstance(detector.detect(np.zeros((8, 8, 3), dtype=np.uint8)), list)


def test_the_model_trains_on_the_device_and_returns_to_the_cpu_before_saving(
    module: ModuleType, small_run: SimpleNamespace, monkeypatch
) -> None:
    chosen = torch.device("cpu")  # no GPU here: the order of the moves is what counts
    events: list[str] = []
    real_to, real_cpu = torch.nn.Module.to, torch.nn.Module.cpu
    real_train, real_save = module.train, torch.save

    def spy_to(self, *args, **kwargs):
        events.append("model to device")
        return real_to(self, *args, **kwargs)

    def spy_cpu(self):
        events.append("model to cpu")
        return real_cpu(self)

    def spy_train(*args, **kwargs):
        assert chosen in args or kwargs.get("device") == chosen
        events.append("train")
        return real_train(*args, **kwargs)

    def spy_save(state, path):
        if Path(path).name == "look_thermal.pt":
            events.append("save weights")
        return real_save(state, path)

    monkeypatch.setattr(module, "resolve_device", lambda _: chosen)
    monkeypatch.setattr(torch.nn.Module, "to", spy_to)
    monkeypatch.setattr(torch.nn.Module, "cpu", spy_cpu)
    monkeypatch.setattr(module, "train", spy_train)
    monkeypatch.setattr(torch, "save", spy_save)
    assert run_main(monkeypatch, module, "--device", "cuda") == 0
    assert events == ["model to device", "train", "model to cpu", "save weights"]


def test_measuring_uses_the_device_and_writes_no_weights(
    module: ModuleType, small_run: SimpleNamespace, monkeypatch, capsys
) -> None:
    devices: list[torch.device | None] = []
    real_train = module.train

    def spy_train(*args, **kwargs):
        devices.append(kwargs.get("device"))
        return real_train(*args, **kwargs)

    monkeypatch.setattr(module, "train", spy_train)
    monkeypatch.setattr(module, "MEASURE_BATCHES", 1)
    monkeypatch.setattr(module, "WARM_UP_BATCHES", 1)
    assert run_main(monkeypatch, module, "--measure") == 0
    assert devices == [torch.device("cpu"), torch.device("cpu")]  # warm-up, then timed
    out = capsys.readouterr().out
    for line in ("seconds per batch:", "minutes per epoch:", "minutes for 1 epochs:"):
        assert line in out
    assert not small_run.models.exists()


def test_the_trained_on_record_names_the_gpu(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda: "Tesla T4")
    assert module.device_name(torch.device("cuda")) == "Tesla T4"


def test_a_missing_gpu_fails_before_any_frames_are_decoded(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_decoding(*_: object) -> None:
        raise AssertionError("frames were decoded before the device was checked")

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(module, "sample_clip", no_decoding)
    with pytest.raises(SystemExit, match="cannot see a CUDA GPU"):
        run_main(monkeypatch, module, "--device", "cuda")
