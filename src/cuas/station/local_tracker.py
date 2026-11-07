"""Follows detections across frames in one camera, using ByteTrack's two-stage association.

High-score boxes are matched first. Low-score boxes then get a chance to continue existing
tracks, which keeps faint targets alive without letting them start tracks of their own.
Matching uses distance rather than box overlap, because small targets at a low frame rate
rarely overlap between frames.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from cuas.station.detector import Box

Point = tuple[float, float]


def centre(box: Box) -> Point:
    return (box.x1 + box.x2) / 2.0, (box.y1 + box.y2) / 2.0


@dataclass
class LocalTrack:
    track_id: int
    position: Point
    velocity: Point = (0.0, 0.0)
    missed: int = 0
    history: list[Point | None] = field(default_factory=list)
    """Where the track was on each update, or ``None`` when it was not seen."""
    scores: defaultdict[str, list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def predicted(self) -> Point:
        steps = self.missed + 1
        return (
            self.position[0] + self.velocity[0] * steps,
            self.position[1] + self.velocity[1] * steps,
        )

    def see(self, box: Box) -> None:
        steps = self.missed + 1
        x, y = centre(box)
        self.velocity = (
            (x - self.position[0]) / steps,
            (y - self.position[1]) / steps,
        )
        self.position = (x, y)
        self.missed = 0
        self.history.append((x, y))
        self.scores[box.class_name].append(box.score)

    def miss(self) -> None:
        self.missed += 1
        self.history.append(None)

    def confidence(self) -> dict[str, float]:
        """Average score per class over the track (docs/design.md A7)."""
        return {name: sum(s) / len(s) for name, s in self.scores.items()}


class LocalTracker:
    def __init__(self, high_score: float, max_step_px: float, max_missed: int) -> None:
        self._high_score = high_score
        self._max_step_px = max_step_px
        self._max_missed = max_missed
        self._next_id = 1
        self.tracks: list[LocalTrack] = []

    def update(self, boxes: Sequence[Box]) -> list[LocalTrack]:
        """Take one frame's boxes and return the tracks seen in that frame."""
        high = [b for b in boxes if b.score >= self._high_score]
        low = [b for b in boxes if b.score < self._high_score]
        unmatched_tracks, unmatched_high, seen = self._match(self.tracks, high)
        leftover_tracks, _, seen_low = self._match(unmatched_tracks, low)
        for track in leftover_tracks:
            track.miss()
        self.tracks = [t for t in self.tracks if t.missed <= self._max_missed]
        for box in unmatched_high:
            track = LocalTrack(self._next_id, centre(box))
            self._next_id += 1
            track.see(box)
            self.tracks.append(track)
            seen.append(track)
        return seen + seen_low

    def _match(
        self, tracks: list[LocalTrack], boxes: list[Box]
    ) -> tuple[list[LocalTrack], list[Box], list[LocalTrack]]:
        """Pair tracks and boxes within reach. Returns what is left of each, and those seen."""
        if not tracks or not boxes:
            return list(tracks), list(boxes), []
        cost = np.array(
            [
                [np.hypot(*np.subtract(track.predicted(), centre(b))) for b in boxes]
                for track in tracks
            ]
        )
        pairs = [
            (r, c)
            for r, c in zip(*linear_sum_assignment(cost), strict=True)
            if cost[r, c] <= self._max_step_px
        ]
        for r, c in pairs:
            tracks[r].see(boxes[c])
        used_tracks, used_boxes = {r for r, _ in pairs}, {c for _, c in pairs}
        return (
            [t for i, t in enumerate(tracks) if i not in used_tracks],
            [b for i, b in enumerate(boxes) if i not in used_boxes],
            [tracks[r] for r, _ in pairs],
        )
