"""Mixes recordings with noise: louder noise (lower SNR) with distance and wind (design.md A2)."""

import math

import numpy as np

from cuas.config import MixingSettings

DB_PER_DECADE = 20.0
POWER_DB = 10.0
MIN_RANGE_M = 1.0


def snr_for(range_m: float, wind_mps: float, settings: MixingSettings) -> float:
    """Sound falls 6 dB per doubling of distance, and wind costs a fixed amount per m/s."""
    distance = max(range_m, MIN_RANGE_M) / settings.reference_range_m
    snr = (
        settings.reference_snr_db
        - DB_PER_DECADE * math.log10(distance)
        - settings.wind_loss_db_per_mps * wind_mps
    )
    return max(settings.min_snr_db, min(settings.max_snr_db, snr))


def fit_length(samples: np.ndarray, length: int, start: int = 0) -> np.ndarray:
    """A window of exactly ``length`` samples, looping if the recording is shorter."""
    positions = (np.arange(length) + start) % samples.size
    return samples[positions]


def mix_at_snr(signal: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    """Scales the noise so the mix has this signal-to-noise ratio."""
    signal_power = float(np.mean(signal**2))
    noise_power = float(np.mean(noise**2))
    if signal_power == 0.0 or noise_power == 0.0:
        return signal + noise
    wanted = signal_power / 10.0 ** (snr_db / POWER_DB)
    return signal + noise * math.sqrt(wanted / noise_power)
