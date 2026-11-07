"""Audio classifier: a small CNN over a log-mel spectrogram. It only ever hears samples."""

from pathlib import Path

import numpy as np
import torch
from torch import nn

from cuas.config import SoundSettings
from cuas.station.mel import log_mel

CHANNELS = (16, 32, 64)
KERNEL = 3
PADDING = 1
POOL = 2


class SoundNet(nn.Module):
    """Small enough to train on a laptop CPU in minutes."""

    def __init__(self, classes: int) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        inputs = 1
        for outputs in CHANNELS:
            layers += [
                nn.Conv2d(inputs, outputs, KERNEL, padding=PADDING),
                nn.BatchNorm2d(outputs),
                nn.ReLU(),
                nn.MaxPool2d(POOL),
            ]
            inputs = outputs
        self.features = nn.Sequential(*layers, nn.AdaptiveAvgPool2d(1), nn.Flatten())
        self.classifier = nn.Linear(inputs, classes)

    def forward(self, batch: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.features(batch))


def to_batch(windows: list[np.ndarray], settings: SoundSettings) -> torch.Tensor:
    """One-channel spectrograms ready for the network."""
    spectrograms = [log_mel(window, settings) for window in windows]
    return torch.from_numpy(np.stack(spectrograms)).float().unsqueeze(1)


class SoundModel:
    def __init__(self, net: nn.Module, settings: SoundSettings) -> None:
        self._net = net.eval()
        self._settings = settings

    @torch.inference_mode()
    def classify(self, window: np.ndarray) -> dict[str, float]:
        """A probability for every class, for one window of samples."""
        logits = self._net(to_batch([window], self._settings))
        probabilities = torch.softmax(logits, dim=1)[0].tolist()
        return dict(zip(self._settings.classes, probabilities, strict=True))


def load_sound_model(settings: SoundSettings, path: Path) -> SoundModel:
    net = SoundNet(len(settings.classes))
    net.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
    return SoundModel(net, settings)
