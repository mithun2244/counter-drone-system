"""Decoding recorded clips into arrays. Knows nothing about labels."""

import wave
from collections.abc import Collection
from math import gcd
from pathlib import Path

import av
import numpy as np
from scipy.signal import resample_poly

PCM_16_BYTES = 2
PCM_16_SCALE = 32768.0


def decode_frames(path: Path, indices: Collection[int]) -> dict[int, np.ndarray]:
    """The requested frames as height x width x 3 RGB arrays."""
    wanted = set(indices)
    last = max(wanted, default=-1)
    frames: dict[int, np.ndarray] = {}
    with av.open(str(path)) as container:
        container.streams.video[0].thread_type = "AUTO"
        for index, frame in enumerate(container.decode(video=0)):
            if index in wanted:
                frames[index] = frame.to_ndarray(format="rgb24")
            if index >= last:
                break
    return frames


def frame_rate(path: Path) -> float:
    with av.open(str(path)) as container:
        return float(container.streams.video[0].average_rate)


def decode_every(path: Path, step: int) -> list[np.ndarray]:
    """Every ``step``-th frame, starting with the first."""
    frames: list[np.ndarray] = []
    with av.open(str(path)) as container:
        container.streams.video[0].thread_type = "AUTO"
        for index, frame in enumerate(container.decode(video=0)):
            if index % step == 0:
                frames.append(frame.to_ndarray(format="rgb24"))
    return frames


def frame_count(path: Path) -> int:
    with av.open(str(path)) as container:
        container.streams.video[0].thread_type = "AUTO"
        return sum(1 for _ in container.decode(video=0))


def read_wav(path: Path, sample_rate: int) -> np.ndarray:
    """A 16-bit PCM file as mono samples from -1 to 1, at the requested rate."""
    with wave.open(str(path), "rb") as file:
        if file.getsampwidth() != PCM_16_BYTES:
            raise ValueError(f"{path.name} is not 16-bit PCM")
        channels, rate = file.getnchannels(), file.getframerate()
        raw = file.readframes(file.getnframes())
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float64) / PCM_16_SCALE
    mono = samples.reshape(-1, channels).mean(axis=1)
    if rate == sample_rate:
        return mono
    divisor = gcd(rate, sample_rate)
    return resample_poly(mono, sample_rate // divisor, rate // divisor)
