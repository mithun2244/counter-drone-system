"""Track-before-detect, demo version: seen in M of the last N frames along a smooth path."""

import math
from collections.abc import Sequence

Point = tuple[float, float]


def is_confirmed(
    history: Sequence[Point | None], m: int, n: int, max_step_px: float
) -> bool:
    """Rejects single-frame noise and keeps faint but consistent targets (docs/design.md A3)."""
    window = history[-n:]
    if sum(point is not None for point in window) < m:
        return False
    last: Point | None = None
    gap = 1
    for point in window:
        if point is None:
            gap += 1
            continue
        if last is not None and math.dist(last, point) > max_step_px * gap:
            return False
        last, gap = point, 1
    return True
