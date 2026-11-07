import math

import numpy as np
import pytest

from cuas.config import MixingSettings, SiteConfig
from cuas.sim.mixing import fit_length, mix_at_snr, snr_for

TOLERANCE_DB = 0.1


@pytest.fixture
def settings(site: SiteConfig) -> MixingSettings:
    return site.station_ai.sound.mixing


def wide_open(settings: MixingSettings) -> MixingSettings:
    return settings.model_copy(update={"min_snr_db": -100.0, "max_snr_db": 100.0})


def measured_snr(signal: np.ndarray, mixed: np.ndarray) -> float:
    noise = mixed - signal
    return 10.0 * math.log10(float(np.mean(signal**2)) / float(np.mean(noise**2)))


def test_snr_at_the_reference_range_with_no_wind_is_the_reference(
    settings: MixingSettings,
) -> None:
    open_settings = wide_open(settings)
    value = snr_for(settings.reference_range_m, 0.0, open_settings)
    assert value == pytest.approx(settings.reference_snr_db)


def test_doubling_the_distance_costs_six_decibels(settings: MixingSettings) -> None:
    open_settings = wide_open(settings)
    near = snr_for(100.0, 0.0, open_settings)
    far = snr_for(200.0, 0.0, open_settings)
    assert near - far == pytest.approx(20.0 * math.log10(2.0))


def test_wind_lowers_the_snr_by_its_configured_amount(settings: MixingSettings) -> None:
    open_settings = wide_open(settings)
    calm = snr_for(100.0, 0.0, open_settings)
    windy = snr_for(100.0, 10.0, open_settings)
    assert calm - windy == pytest.approx(10.0 * settings.wind_loss_db_per_mps)


def test_snr_stays_within_its_limits(settings: MixingSettings) -> None:
    assert snr_for(1e9, 100.0, settings) == settings.min_snr_db
    assert snr_for(0.0, 0.0, settings) <= settings.max_snr_db


@pytest.mark.parametrize("target", [20.0, 10.0, 0.0, -10.0])
def test_a_mix_has_the_snr_it_was_asked_for(target: float) -> None:
    rng = np.random.default_rng(0)
    signal = rng.normal(0.0, 0.3, 16000)
    noise = rng.normal(0.0, 0.7, 16000)
    assert measured_snr(signal, mix_at_snr(signal, noise, target)) == pytest.approx(
        target, abs=TOLERANCE_DB
    )


def test_mixing_keeps_the_signal_itself_unscaled() -> None:
    signal = np.ones(100)
    noise = np.zeros(100)
    assert np.array_equal(mix_at_snr(signal, noise, 10.0), signal)


def test_silence_does_not_break_the_mix() -> None:
    silence = np.zeros(10)
    assert np.array_equal(mix_at_snr(silence, np.ones(10), 10.0), np.ones(10))


def test_a_short_recording_loops_to_the_window_length() -> None:
    samples = np.array([1.0, 2.0, 3.0])
    assert fit_length(samples, 7).tolist() == [1.0, 2.0, 3.0, 1.0, 2.0, 3.0, 1.0]


def test_a_window_can_start_anywhere_and_wraps() -> None:
    samples = np.array([1.0, 2.0, 3.0, 4.0])
    assert fit_length(samples, 3, start=3).tolist() == [4.0, 1.0, 2.0]
