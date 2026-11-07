from pathlib import Path

import numpy as np
import pytest
import torch
from torch import nn

from cuas.config import SiteConfig, SoundSettings
from cuas.station.sound import SoundModel, SoundNet, load_sound_model, to_batch


@pytest.fixture
def settings(site: SiteConfig) -> SoundSettings:
    return site.station_ai.sound


def tone(hz: float, settings: SoundSettings, rng: np.random.Generator) -> np.ndarray:
    times = np.arange(settings.window_samples) / settings.sample_rate
    noise = rng.normal(0.0, 0.05, times.size)
    return np.sin(2 * np.pi * hz * times + rng.uniform(0, 6.28)) + noise


def test_batch_shape_is_one_channel_spectrograms(settings: SoundSettings) -> None:
    window = np.zeros(settings.window_samples)
    batch = to_batch([window, window], settings)
    assert batch.shape[:3] == (2, 1, settings.n_mels)


def test_classify_gives_a_probability_for_every_class(settings: SoundSettings) -> None:
    torch.manual_seed(0)
    model = SoundModel(SoundNet(len(settings.classes)), settings)
    window = np.random.default_rng(0).normal(0.0, 1.0, settings.window_samples)
    result = model.classify(window)
    assert list(result) == list(settings.classes)
    assert sum(result.values()) == pytest.approx(1.0)


def test_the_network_can_learn_to_tell_two_tones_apart(settings: SoundSettings) -> None:
    """The smallest proof that training works: no real recordings needed."""
    two_classes = settings.model_copy(update={"classes": ("low", "high")})
    torch.manual_seed(0)
    rng = np.random.default_rng(0)
    net = SoundNet(2)
    optimizer = torch.optim.AdamW(net.parameters(), lr=0.003)
    loss_function = nn.CrossEntropyLoss()
    net.train()
    first_loss = None
    for _ in range(60):
        windows = [tone(300.0, two_classes, rng) for _ in range(4)]
        windows += [tone(3000.0, two_classes, rng) for _ in range(4)]
        targets = torch.tensor([0] * 4 + [1] * 4)
        loss = loss_function(net(to_batch(windows, two_classes)), targets)
        first_loss = first_loss if first_loss is not None else loss.item()
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
    assert loss.item() < first_loss / 2
    model = SoundModel(net, two_classes)
    assert model.classify(tone(300.0, two_classes, rng))["low"] > 0.5
    assert model.classify(tone(3000.0, two_classes, rng))["high"] > 0.5


def test_saved_weights_load_back_to_the_same_answer(
    settings: SoundSettings, tmp_path: Path
) -> None:
    torch.manual_seed(0)
    net = SoundNet(len(settings.classes))
    path = tmp_path / "sound.pt"
    torch.save(net.state_dict(), path)
    window = np.random.default_rng(1).normal(0.0, 1.0, settings.window_samples)
    original = SoundModel(net, settings).classify(window)
    assert load_sound_model(settings, path).classify(window) == pytest.approx(original)
