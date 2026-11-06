"""Decoding recorded clips into arrays. Knows nothing about labels."""

from collections.abc import Collection
from pathlib import Path

import av
import numpy as np


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


def frame_count(path: Path) -> int:
    with av.open(str(path)) as container:
        container.streams.video[0].thread_type = "AUTO"
        return sum(1 for _ in container.decode(video=0))
