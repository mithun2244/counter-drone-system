import numpy as np
import pytest

from cuas.config import SiteConfig, SoundSettings
from cuas.station.mel import hz_to_mel, log_mel, mel_filterbank, mel_to_hz


@pytest.fixture
def settings(site: SiteConfig) -> SoundSettings:
    return site.station_ai.sound


def tone(hz: float, settings: SoundSettings) -> np.ndarray:
    times = np.arange(settings.window_samples) / settings.sample_rate
    return np.sin(2 * np.pi * hz * times)


def test_mel_scale_known_answers() -> None:
    assert hz_to_mel(0.0) == 0.0
    assert hz_to_mel(700.0) == pytest.approx(2595.0 * np.log10(2.0))
    assert mel_to_hz(hz_to_mel(1000.0)) == pytest.approx(1000.0)


def test_filterbank_has_the_right_shape_and_no_negative_weights(
    settings: SoundSettings,
) -> None:
    filters = mel_filterbank(settings.sample_rate, settings.n_fft, settings.n_mels)
    assert filters.shape == (settings.n_mels, settings.n_fft // 2 + 1)
    assert filters.min() >= 0.0
    assert (filters.max(axis=1) > 0.0).all()  # no empty filter


def test_filter_centres_rise_with_frequency(settings: SoundSettings) -> None:
    filters = mel_filterbank(settings.sample_rate, settings.n_fft, settings.n_mels)
    centres = filters.argmax(axis=1)
    assert (np.diff(centres) >= 0).all()


def test_spectrogram_shape_is_known(settings: SoundSettings) -> None:
    mel = log_mel(tone(1000.0, settings), settings)
    frames = (settings.window_samples - settings.n_fft) // settings.hop + 1
    assert mel.shape == (settings.n_mels, frames)


@pytest.mark.parametrize("hz", [250.0, 1000.0, 4000.0])
def test_a_tone_peaks_in_the_filter_covering_its_frequency(
    settings: SoundSettings, hz: float
) -> None:
    mel = log_mel(tone(hz, settings), settings)
    peak_filter = int(mel.mean(axis=1).argmax())
    filters = mel_filterbank(settings.sample_rate, settings.n_fft, settings.n_mels)
    hz_per_bin = settings.sample_rate / settings.n_fft
    bin_at_tone = round(hz / hz_per_bin)
    assert filters[peak_filter, bin_at_tone] > 0.0


def test_a_higher_tone_peaks_in_a_higher_filter(settings: SoundSettings) -> None:
    low = log_mel(tone(500.0, settings), settings).mean(axis=1).argmax()
    high = log_mel(tone(4000.0, settings), settings).mean(axis=1).argmax()
    assert high > low


def test_overall_loudness_carries_no_signal(settings: SoundSettings) -> None:
    quiet = log_mel(0.01 * tone(1000.0, settings), settings)
    loud = log_mel(tone(1000.0, settings), settings)
    assert quiet == pytest.approx(loud, abs=1e-6)


def test_silence_does_not_break(settings: SoundSettings) -> None:
    assert np.isfinite(log_mel(np.zeros(settings.window_samples), settings)).all()
