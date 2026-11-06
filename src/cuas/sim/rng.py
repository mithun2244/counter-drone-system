"""Named random streams, so each noise source is independent and reproducible."""

import zlib

import numpy as np


def stream(seed: int, *keys: str) -> np.random.Generator:
    """A generator fixed by the seed and names. ``crc32`` is stable; ``hash()`` is salted."""
    return np.random.default_rng([seed, *(zlib.crc32(key.encode()) for key in keys)])
