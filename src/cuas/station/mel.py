"""Log-mel spectrogram in numpy. Current ``librosa`` needs Python 3.12, and this is small."""

import numpy as np

from cuas.config import SoundSettings

MEL_SCALE = 2595.0
MEL_BREAK_HZ = 700.0
RELATIVE_FLOOR = 1e-10
NYQUIST_DIVISOR = 2.0


def hz_to_mel(hz: np.ndarray | float) -> np.ndarray | float:
    return MEL_SCALE * np.log10(1.0 + np.asarray(hz) / MEL_BREAK_HZ)


def mel_to_hz(mel: np.ndarray | float) -> np.ndarray | float:
    return MEL_BREAK_HZ * (10.0 ** (np.asarray(mel) / MEL_SCALE) - 1.0)


def mel_filterbank(sample_rate: int, n_fft: int, n_mels: int) -> np.ndarray:
    """Triangular filters, ``n_mels`` x ``n_fft // 2 + 1``, evenly spaced on the mel scale."""
    top = hz_to_mel(sample_rate / NYQUIST_DIVISOR)
    edges = mel_to_hz(np.linspace(0.0, top, n_mels + 2))
    bins = np.linspace(0.0, sample_rate / NYQUIST_DIVISOR, n_fft // 2 + 1)
    filters = np.zeros((n_mels, bins.size))
    for index in range(n_mels):
        low, middle, high = edges[index : index + 3]
        rising = (bins - low) / (middle - low)
        falling = (high - bins) / (high - middle)
        filters[index] = np.clip(np.minimum(rising, falling), 0.0, None)
    return filters


def log_mel(samples: np.ndarray, settings: SoundSettings) -> np.ndarray:
    """``n_mels`` x frames. Each window is normalised, so overall loudness carries no signal."""
    window = np.hanning(settings.n_fft)
    starts = range(0, samples.size - settings.n_fft + 1, settings.hop)
    frames = np.stack([samples[s : s + settings.n_fft] * window for s in starts])
    power = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    filters = mel_filterbank(settings.sample_rate, settings.n_fft, settings.n_mels)
    energy = power @ filters.T
    # Relative to the window's own peak, so a quiet recording looks like a loud one.
    peak = energy.max() or 1.0
    mel = np.log10(energy + RELATIVE_FLOOR * peak).T
    spread = mel.std()
    return (mel - mel.mean()) / spread if spread > 0 else mel - mel.mean()
