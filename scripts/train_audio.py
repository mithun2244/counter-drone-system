"""Train the audio classifier, keeping the epoch that does best on validation clips.

The test split is never read here. Training noise comes only from training clips.
"""

import json
import sys
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


def clip_accuracy(
    model: SoundModel, clips: list[tuple[str, np.ndarray]], settings: SoundSettings
) -> float:
    """Each clip is judged on the average of its windows."""
    correct = 0
    for label, audio in clips:
        starts = range(
            0, max(audio.size - settings.window_samples, 1), settings.window_samples
        )
        scores = [
            model.classify(fit_length(audio, settings.window_samples, start))
            for start in starts
        ]
        mean = {
            name: float(np.mean([s[name] for s in scores])) for name in settings.classes
        }
        correct += max(mean, key=mean.get) == label
    return correct / len(clips)


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
    train_clips = load_clips([c for c in clips if c.split == "train"], settings)
    val_clips = load_clips([c for c in clips if c.split == "val"], settings)
    noises = [audio for label, audio in train_clips if label == NOISE_LABEL]
    print(f"{len(train_clips)} training clips, {len(val_clips)} validation clips")

    net = SoundNet(len(settings.classes))
    optimizer = torch.optim.AdamW(
        net.parameters(), lr=training.learning_rate, weight_decay=training.weight_decay
    )
    loss_function = nn.CrossEntropyLoss()
    best_accuracy, best_epoch, best_state = -1.0, -1, None
    for epoch in range(training.epochs):
        net.train()
        windows, targets = [], []
        for label, audio in train_clips:
            for _ in range(training.windows_per_clip):
                windows.append(training_window(audio, label, noises, settings, rng))
                targets.append(settings.classes.index(label))
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
        accuracy = clip_accuracy(SoundModel(net, settings), val_clips, settings)
        print(f"epoch {epoch} loss {np.mean(losses):.3f} val accuracy {accuracy:.3f}")
        # Ties keep the later epoch, which has seen more data.
        if accuracy >= best_accuracy:
            best_accuracy, best_epoch = accuracy, epoch
            best_state = {k: v.clone() for k, v in net.state_dict().items()}

    MODELS_DIR.mkdir(exist_ok=True)
    weights = MODELS_DIR / "sound.pt"
    torch.save(best_state, weights)
    record = {
        "weights_sha256": sha256_of(weights),
        "manifest_sha256": sha256_of(CONFIG_DIR / MANIFEST_NAME),
        "classes": list(settings.classes),
        "best_epoch": best_epoch,
        "validation_accuracy": best_accuracy,
        "validation_clips": len(val_clips),
    }
    (MODELS_DIR / "sound.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
    print(f"kept epoch {best_epoch}, validation accuracy {best_accuracy:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
