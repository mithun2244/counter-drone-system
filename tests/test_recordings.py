import wave
from pathlib import Path

import av
import numpy as np
import pytest

from cuas.recordings import (
    decode_every,
    decode_frames,
    frame_count,
    frame_rate,
    read_wav,
)

FRAMES = 6
WIDTH, HEIGHT = 32, 16


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    """A small clip whose frames get brighter, so each one can be told apart."""
    path = tmp_path / "clip.mp4"
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = WIDTH, HEIGHT, "yuv420p"
        for index in range(FRAMES):
            pixels = np.full((HEIGHT, WIDTH, 3), 20 + index * 40, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path


def test_frame_count_counts_every_frame(clip: Path) -> None:
    assert frame_count(clip) == FRAMES


def test_requested_frames_come_back_as_rgb_arrays(clip: Path) -> None:
    frames = decode_frames(clip, [1, 4])
    assert sorted(frames) == [1, 4]
    assert frames[1].shape == (HEIGHT, WIDTH, 3)
    assert frames[1].dtype == np.uint8
    assert frames[4].mean() > frames[1].mean()


def test_frame_rate_comes_from_the_clip(clip: Path) -> None:
    assert frame_rate(clip) == 30.0


def test_decode_every_keeps_every_nth_frame_from_the_first(clip: Path) -> None:
    frames = decode_every(clip, 2)
    assert len(frames) == 3
    assert frames[0].mean() < frames[1].mean() < frames[2].mean()


def test_requesting_nothing_gives_nothing(clip: Path) -> None:
    assert decode_frames(clip, []) == {}


def write_wav(path: Path, samples: np.ndarray, rate: int, channels: int = 1) -> None:
    with wave.open(str(path), "wb") as file:
        file.setnchannels(channels)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(samples.astype("<i2").tobytes())


def test_read_wav_scales_to_plus_or_minus_one(tmp_path: Path) -> None:
    path = tmp_path / "a.wav"
    write_wav(path, np.array([0, 16384, -16384]), 16000)
    assert read_wav(path, 16000).tolist() == pytest.approx([0.0, 0.5, -0.5])


def test_read_wav_averages_stereo_to_mono(tmp_path: Path) -> None:
    path = tmp_path / "a.wav"
    write_wav(path, np.array([16384, 0, 0, 16384]), 16000, channels=2)
    assert read_wav(path, 16000).tolist() == pytest.approx([0.25, 0.25])


def test_read_wav_resamples_and_keeps_the_pitch(tmp_path: Path) -> None:
    path = tmp_path / "a.wav"
    rate, seconds, hz = 44100, 1.0, 440.0
    times = np.arange(int(rate * seconds)) / rate
    write_wav(path, 20000 * np.sin(2 * np.pi * hz * times), rate)
    samples = read_wav(path, 16000)
    assert samples.size == 16000
    peak = np.abs(np.fft.rfft(samples)).argmax()  # one bin per hertz for one second
    assert peak == pytest.approx(hz, abs=1)


def test_read_wav_refuses_other_sample_widths(tmp_path: Path) -> None:
    path = tmp_path / "a.wav"
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(1)
        file.setframerate(8000)
        file.writeframes(b"\x00\x01")
    with pytest.raises(ValueError, match="16-bit"):
        read_wav(path, 8000)
