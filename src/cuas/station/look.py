"""Turns a camera's frames into class confidences: detector, then tracker, then M-of-N.

This is the truth boundary. Everything here sees pixels only: no label, path or target ID.
"""

from collections.abc import Callable, Sequence

import numpy as np

from cuas.config import LookSettings
from cuas.station.confirm import is_confirmed
from cuas.station.detector import Box
from cuas.station.local_tracker import LocalTracker

DetectFn = Callable[[np.ndarray], list[Box]]


class CachedDetector:
    """Remembers each frame's boxes, because several streams may look at the same clip."""

    def __init__(self, detect: DetectFn) -> None:
        self._detect = detect
        self._boxes: dict[str, list[Box]] = {}

    def boxes(self, frame_key: str, frame: np.ndarray) -> list[Box]:
        """``frame_key`` must be opaque, such as a clip hash and frame number."""
        if frame_key not in self._boxes:
            self._boxes[frame_key] = self._detect(frame)
        return self._boxes[frame_key]


class LookStream:
    """One sensor following one thing. Unconfirmed looks report zero, which is a real answer."""

    def __init__(
        self,
        settings: LookSettings,
        classes: Sequence[str],
        high_score: float,
        frame_width: int,
    ) -> None:
        self._settings = settings
        self._classes = tuple(classes)
        self._max_step_px = settings.max_step_fraction * frame_width
        self._tracker = LocalTracker(high_score, self._max_step_px, settings.max_missed)

    def update(self, boxes: Sequence[Box]) -> dict[str, float]:
        """Take one frame's boxes and return a confidence for every class."""
        self._tracker.update(boxes)
        settings = self._settings
        confidence = dict.fromkeys(self._classes, 0.0)
        for track in self._tracker.tracks:
            confirmed = is_confirmed(
                track.history, settings.m, settings.n, self._max_step_px
            )
            if track.missed == 0 and confirmed:
                for name, score in track.confidence().items():
                    confidence[name] = max(confidence[name], score)
        return confidence
