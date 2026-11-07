from pathlib import Path

import av
import numpy as np
import pytest

from cuas.recordings import decode_every, decode_frames, frame_count, frame_rate

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
