"""Behaviour features and the move clue (docs/design.md A7).

Only fresh fixes count: positions the tracker triangulated in that batch, never its coasting
predictions. Measured on Phase 3 tracks, hovering and long fast straight flight separate drones
from birds; sharp turns and straightness alone do not, because birds turn constantly and often
fly straight for seconds at a time.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from cuas.config import MoveSettings

HOVERING, FAST_STRAIGHT, BIRD_LIKE = (
    "hovering",
    "fast straight flight",
    "bird-like flight",
)
MIN_FIXES = 4
TINY_PATH_M = 1e-6
SLOWEST_MEAN_MPS = 0.1  # keeps speed variation finite for a target at rest


@dataclass(frozen=True)
class Fix:
    t: float
    position: np.ndarray
    velocity: np.ndarray


@dataclass(frozen=True)
class Features:
    speed_mps: float
    speed_cv: float
    straightness: float
    hover_fraction: float


def features(fixes: Sequence[Fix], settings: MoveSettings) -> Features | None:
    """Features over the last ``window_s`` of fixes, or ``None`` before enough history."""
    now = fixes[-1].t
    window = [f for f in fixes if f.t >= now - settings.window_s]
    if len(window) < MIN_FIXES or window[-1].t - window[0].t < settings.min_history_s:
        return None
    ground = np.array([f.position[:2] for f in window])
    speeds = np.array([np.linalg.norm(f.velocity[:2]) for f in window])
    path = float(np.sum(np.linalg.norm(np.diff(ground, axis=0), axis=1)))
    chord = float(np.linalg.norm(ground[-1] - ground[0]))
    mean = float(speeds.mean())
    return Features(
        speed_mps=mean,
        speed_cv=float(speeds.std()) / max(mean, SLOWEST_MEAN_MPS),
        straightness=chord / path if path > TINY_PATH_M else 0.0,
        hover_fraction=_hover_fraction(fixes, window, settings),
    )


def _hover_fraction(
    fixes: Sequence[Fix], window: Sequence[Fix], settings: MoveSettings
) -> float:
    """Share of the window moving slower than hover speed, judged over ``hover_baseline_s``.

    Position change over seconds is steadier than the filter's velocity, which jitters above
    1 m/s even when a target is still.
    """
    slow = []
    for fix in window:
        earlier = [f for f in fixes if f.t <= fix.t - settings.hover_baseline_s]
        if earlier:
            base = earlier[-1]
            moved = float(np.linalg.norm(fix.position[:2] - base.position[:2]))
            slow.append(moved / (fix.t - base.t) < settings.hover_speed_mps)
    return float(np.mean(slow)) if slow else 0.0


class MoveClue:
    """One track's behaviour, fed fresh fixes only."""

    def __init__(self, settings: MoveSettings) -> None:
        self._settings = settings
        self._fixes: list[Fix] = []
        self._latest: Features | None = None
        self._fast_s = 0.0
        self._last_fast_t: float | None = None

    @property
    def latest(self) -> Features | None:
        return self._latest

    def add(self, fix: Fix) -> None:
        settings = self._settings
        self._fixes.append(fix)
        keep_after = fix.t - settings.window_s - settings.hover_baseline_s
        self._fixes = [f for f in self._fixes if f.t >= keep_after]
        self._latest = features(self._fixes, settings)
        if self._latest is not None and self._is_fast(self._latest):
            gap = None if self._last_fast_t is None else fix.t - self._last_fast_t
            in_a_row = gap is not None and gap <= settings.fast_max_gap_s
            self._fast_s = self._fast_s + gap if in_a_row else 0.0
            self._last_fast_t = fix.t
        else:
            self._fast_s, self._last_fast_t = 0.0, None

    def reason(self) -> str | None:
        """What the behaviour looks like, or ``None`` while there is too little history."""
        if self._latest is None:
            return None
        if self._latest.hover_fraction >= self._settings.hover_fraction:
            return HOVERING
        if self._fast_s >= self._settings.fast_persistence_s:
            return FAST_STRAIGHT
        return BIRD_LIKE

    def p_move(self) -> float | None:
        """P(drone) from behaviour, or ``None`` while there is too little history."""
        reason = self.reason()
        if reason is None:
            return None
        settings = self._settings
        return settings.bird_like if reason == BIRD_LIKE else settings.drone_like

    def _is_fast(self, f: Features) -> bool:
        settings = self._settings
        return (
            f.speed_mps >= settings.fast_speed_mps
            and f.straightness >= settings.fast_straightness
            and f.speed_cv <= settings.fast_speed_cv
        )
