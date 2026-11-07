"""Train the audio classifier, keeping the epoch that does best on validation clips.

The test split is never read here. Training noise comes only from training clips.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from torch import nn

from cuas.config import SoundSettings, load_site
from cuas.hashing import sha256_of
from cuas.media_manifest import MANIFEST_NAME, ClipEntry, load_manifest
from cuas.recordings import read_wav
from cuas.sim.mixing import fit_length, mix_at_snr
from cuas.station.sound import SoundModel, SoundNet, to_batch

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
MODELS_DIR = ROOT / "models"
NOISE_LABEL = "background"
PROBABILITY_FLOOR = 1e-6


def clips_for_training(
    clips: list[ClipEntry],
) -> tuple[list[ClipEntry], list[ClipEntry], list[ClipEntry]]:
    """Training, validation and noise clips. Noise is training clips only; test clips go nowhere."""
    train = [c for c in clips if c.split == "train"]
    val = [c for c in clips if c.split == "val"]
    return train, val, [c for c in train if c.label == NOISE_LABEL]


def load_clips(
    clips: list[ClipEntry], settings: SoundSettings
) -> list[tuple[str, np.ndarray]]:
    return [
        (clip.label, read_wav(DATA_DIR / clip.path, settings.sample_rate))
        for clip in clips
    ]


def training_window(
    audio: np.ndarray,
    label: str,
    noises: list[np.ndarray],
    settings: SoundSettings,
    rng: np.random.Generator,
) -> np.ndarray:
    """A random window, with target sounds mixed into training noise most of the time."""
    size = settings.window_samples
    window = fit_length(audio, size, int(rng.integers(audio.size)))
    if label == NOISE_LABEL or rng.random() < settings.training.clean_fraction:
        return window
    noise = noises[int(rng.integers(len(noises)))]
    noise_window = fit_length(noise, size, int(rng.integers(noise.size)))
    low, high = settings.training.snr_range_db
    return mix_at_snr(window, noise_window, float(rng.uniform(low, high)))


def validate(
    model: SoundModel, clips: list[tuple[str, np.ndarray]], settings: SoundSettings
) -> tuple[float, float]:
    """Balanced log-loss per window, and balanced accuracy per clip.

    Balanced, because plain scores would mostly measure the engine class. The epoch is chosen
    on log-loss: with so few clips, accuracy moves in big steps and mostly rewards luck.
    """
    correct: defaultdict[str, list[bool]] = defaultdict(list)
    losses: defaultdict[str, list[float]] = defaultdict(list)
    size = settings.window_samples
    for label, audio in clips:
        starts = range(0, max(audio.size - size, 1), size)
        scores = [model.classify(fit_length(audio, size, start)) for start in starts]
        losses[label].extend(-np.log(max(s[label], PROBABILITY_FLOOR)) for s in scores)
        mean = {n: float(np.mean([s[n] for s in scores])) for n in settings.classes}
        correct[label].append(max(mean, key=mean.get) == label)
    balanced_loss = float(np.mean([np.mean(v) for v in losses.values()]))
    return balanced_loss, float(np.mean([np.mean(hits) for hits in correct.values()]))


def epoch_windows(
    by_label: dict[str, list[np.ndarray]],
    noises: list[np.ndarray],
    settings: SoundSettings,
    rng: np.random.Generator,
) -> tuple[list[np.ndarray], list[int]]:
    """The same number of windows from every class."""
    windows, targets = [], []
    for label, recordings in sorted(by_label.items()):
        for _ in range(settings.training.windows_per_class):
            audio = recordings[int(rng.integers(len(recordings)))]
            windows.append(training_window(audio, label, noises, settings, rng))
            targets.append(settings.classes.index(label))
    return windows, targets


def main() -> int:
    settings = load_site(CONFIG_DIR).station_ai.sound
    training = settings.training
    torch.manual_seed(training.seed)
    rng = np.random.default_rng(training.seed)
    clips = [
        c
        for c in load_manifest(CONFIG_DIR).clips
        if c.modality == "audio" and c.label in settings.classes
    ]
    train, val, noise = clips_for_training(clips)
    train_clips = load_clips(train, settings)
    val_clips = load_clips(val, settings)
    noises = [audio for _, audio in load_clips(noise, settings)]
    by_label: defaultdict[str, list[np.ndarray]] = defaultdict(list)
    for label, audio in train_clips:
        by_label[label].append(audio)
    print(f"{len(train_clips)} training clips, {len(val_clips)} validation clips")

    net = SoundNet(len(settings.classes))
    optimizer = torch.optim.AdamW(
        net.parameters(), lr=training.learning_rate, weight_decay=training.weight_decay
    )
    loss_function = nn.CrossEntropyLoss()
    best_loss, best_accuracy, best_epoch, best_state = float("inf"), 0.0, -1, None
    for epoch in range(training.epochs):
        net.train()
        windows, targets = epoch_windows(by_label, noises, settings, rng)
        order = rng.permutation(len(windows))
        losses = []
        for start in range(0, len(order), training.batch_size):
            chosen = order[start : start + training.batch_size]
            batch = to_batch([windows[i] for i in chosen], settings)
            loss = loss_function(net(batch), torch.tensor([targets[i] for i in chosen]))
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            losses.append(loss.item())
        val_loss, accuracy = validate(SoundModel(net, settings), val_clips, settings)
        print(
            f"epoch {epoch} train loss {np.mean(losses):.3f} "
            f"val loss {val_loss:.3f} val balanced accuracy {accuracy:.3f}"
        )
        if val_loss < best_loss:
            best_loss, best_accuracy, best_epoch = val_loss, accuracy, epoch
            best_state = {k: v.clone() for k, v in net.state_dict().items()}

    MODELS_DIR.mkdir(exist_ok=True)
    weights = MODELS_DIR / "sound.pt"
    torch.save(best_state, weights)
    record = {
        "weights_sha256": sha256_of(weights),
        "manifest_sha256": sha256_of(CONFIG_DIR / MANIFEST_NAME),
        "classes": list(settings.classes),
        "best_epoch": best_epoch,
        "validation_balanced_loss": best_loss,
        "validation_balanced_accuracy": best_accuracy,
        "validation_clips": len(val_clips),
    }
    (MODELS_DIR / "sound.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
    print(f"kept epoch {best_epoch}, validation balanced accuracy {best_accuracy:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
