"""Known-answer paths for the behaviour features and the move clue."""

import math

import numpy as np
import pytest

from cuas.config import MoveSettings, SiteConfig
from cuas.control.behaviour import Fix, MoveClue, features

TICK = 0.2


@pytest.fixture
def settings(site: SiteConfig) -> MoveSettings:
    return site.classify.move


def path(position_at, seconds: float, velocity_at=None) -> list[Fix]:
    """A fix every tick from t = 0, with the true velocity unless one is given."""
    fixes = []
    for k in range(round(seconds / TICK) + 1):
        t = k * TICK
        p = np.asarray(position_at(t), dtype=float)
        if velocity_at is None:
            v = (
                np.asarray(position_at(t + 1e-3)) - np.asarray(position_at(t - 1e-3))
            ) / 2e-3
        else:
            v = np.asarray(velocity_at(t), dtype=float)
        fixes.append(Fix(t, p, v))
    return fixes


def line(speed: float):
    return lambda t: (speed * t, 0.0, 80.0)


def circle(speed: float, radius: float = 60.0):
    return lambda t: (
        radius * math.cos(speed * t / radius),
        radius * math.sin(speed * t / radius),
        80.0,
    )


def zigzag(speed: float, leg_s: float = 1.0):
    def at(t: float):
        leg, into = divmod(t, leg_s)
        sideways = into if leg % 2 == 0 else leg_s - into
        return (speed * t * 0.7, speed * 0.7 * sideways, 80.0)

    return at


def clue_over(
    fixes: list[Fix], settings: MoveSettings
) -> list[tuple[float, float | None]]:
    clue = MoveClue(settings)
    out = []
    for fix in fixes:
        clue.add(fix)
        out.append((fix.t, clue.p_move()))
    return out


def test_no_clue_before_three_seconds_of_history(settings: MoveSettings) -> None:
    out = clue_over(path(line(50.0), 2.8), settings)
    assert {p for _, p in out} == {None}


def test_a_straight_line_has_known_features(settings: MoveSettings) -> None:
    f = features(path(line(50.0), 6.0), settings)
    assert f.speed_mps == pytest.approx(50.0)
    assert f.speed_cv == pytest.approx(0.0, abs=1e-9)
    assert f.straightness == pytest.approx(1.0)
    assert f.hover_fraction == 0.0


def test_fast_straight_flight_counts_only_after_five_seconds_of_it(
    settings: MoveSettings,
) -> None:
    """Features exist from 3 s, so persistence runs from 3 s and is met at 8 s."""
    out = dict(clue_over(path(line(50.0), 10.0), settings))
    before = {p for t, p in out.items() if 3.0 <= t < 7.99}
    assert before == {settings.bird_like}
    first_drone_like = min(t for t, p in out.items() if p == settings.drone_like)
    assert first_drone_like == pytest.approx(8.0)


def test_hovering_is_drone_like_as_soon_as_there_is_history(
    settings: MoveSettings,
) -> None:
    out = clue_over(path(lambda t: (5.0, -3.0, 60.0), 4.0), settings)
    assert dict(out)[3.0] == settings.drone_like


def test_hover_is_judged_from_position_not_the_filters_jittery_velocity(
    settings: MoveSettings,
) -> None:
    jitter = np.random.default_rng(0)
    fixes = path(
        lambda t: (5.0, -3.0, 60.0),
        6.0,
        velocity_at=lambda t: (*jitter.normal(0.0, 2.0, 2), 0.0),
    )
    assert features(fixes, settings).hover_fraction == 1.0


@pytest.mark.parametrize(
    "shape",
    [circle(12.0), line(12.0), zigzag(50.0)],
    ids=["bird circling", "bird flying straight", "fast sharp turns"],
)
def test_birdlike_and_sharp_turning_paths_stay_bird_like(
    settings: MoveSettings, shape
) -> None:
    """A7's sharp turns and straightness alone no longer count as drone-like."""
    out = clue_over(path(shape, 15.0), settings)
    assert {p for _, p in out if p is not None} == {settings.bird_like}


def test_a_gap_in_fresh_fixes_restarts_persistence(settings: MoveSettings) -> None:
    """Coasting through 6.2 to 7.2 s counts for nothing, so the 5 s start again at 7.4 s."""
    fixes = [f for f in path(line(50.0), 14.0) if not 6.0 < f.t < 7.4]
    out = dict(clue_over(fixes, settings))
    first_drone_like = min(t for t, p in out.items() if p == settings.drone_like)
    assert first_drone_like == pytest.approx(7.4 + settings.fast_persistence_s)


def slows_down(t: float):
    """50 m/s, then 10 m/s from 5 s to 7 s, then 50 m/s again."""
    if t < 5.0:
        return (50.0 * t, 0.0, 80.0)
    if t < 7.0:
        return (250.0 + 10.0 * (t - 5.0), 0.0, 80.0)
    return (270.0 + 50.0 * (t - 7.0), 0.0, 80.0)


def test_slowing_down_restarts_persistence(settings: MoveSettings) -> None:
    """Fast from 3 s, but the slowdown at 5 s breaks it before the 5 s are up at 8 s."""
    out = dict(clue_over(path(slows_down, 12.0), settings))
    assert settings.drone_like not in out.values()


def test_one_odd_fix_does_not_break_a_ten_second_window(settings: MoveSettings) -> None:
    """Features are judged over the window, so a single bad velocity is averaged out."""
    fixes = path(line(50.0), 10.0)
    odd = [
        Fix(f.t, f.position, f.velocity * 0.1) if abs(f.t - 6.0) < 1e-9 else f
        for f in fixes
    ]
    out = dict(clue_over(odd, settings))
    first_drone_like = min(t for t, p in out.items() if p == settings.drone_like)
    assert first_drone_like == pytest.approx(8.0)


def hovers_then_leaves(t: float):
    """Still for 5 s, then off at 12 m/s, like a quadcopter leaving a waypoint."""
    return (5.0, -3.0, 60.0) if t < 5.0 else (5.0 + 12.0 * (t - 5.0), -3.0, 60.0)


def test_hovering_once_seen_stays_for_the_track(settings: MoveSettings) -> None:
    """A7 counts any hovering, and no bird track ever hovered in the Phase 4 measurement."""
    out = dict(clue_over(path(hovers_then_leaves, 25.0), settings))
    assert {p for t, p in out.items() if t >= 3.0} == {settings.drone_like}


def test_fitted_velocity_is_exact_on_a_straight_line(settings: MoveSettings) -> None:
    clue = MoveClue(settings)
    for fix in path(line(50.0), 6.0):
        clue.add(fix)
    assert list(clue.velocity()) == pytest.approx([50.0, 0.0, 0.0])


def test_a_new_track_waits_for_three_seconds_of_fresh_fixes(
    settings: MoveSettings,
) -> None:
    clue = MoveClue(settings)
    fixes = path(line(50.0), 6.0)
    for fix in fixes[:15]:
        clue.add(fix)
    assert clue.velocity() is None  # 2.8 s
    clue.add(fixes[15])
    assert list(clue.velocity()) == pytest.approx([50.0, 0.0, 0.0])  # 3.0 s


def with_gap(start: float, end: float, until: float) -> list[Fix]:
    """Fresh fixes on a 50 m/s line, none strictly between ``start`` and ``end``."""
    return [f for f in path(line(50.0), until) if not start + 1e-9 < f.t < end - 1e-9]


def test_after_a_gap_the_fit_reaches_back_to_a_real_fix(
    settings: MoveSettings,
) -> None:
    """S4 seed 10's gap: at 13.4 s the 5 s window holds only 10.6 to 13.4 s, so the fit
    reaches back to the fix at 8.2 s, 5.2 s old, instead of losing its time to impact."""
    clue = MoveClue(settings)
    for fix in with_gap(8.2, 10.6, 13.4):
        clue.add(fix)
    assert list(clue.velocity()) == pytest.approx([50.0, 0.0, 0.0])


@pytest.mark.parametrize(
    ("now", "fits"),
    [(8.0, True), (8.4, True), (8.6, False)],
    ids=["6.0 s old, the most a live track needs", "6.4 s old", "6.6 s old"],
)
def test_the_fit_never_reaches_back_past_the_maximum_age(
    settings: MoveSettings, now: float, fits: bool
) -> None:
    """Fixes up to 2.0 s, then only the last 2.2 s: the newest fix old enough is at 2.0 s."""
    clue = MoveClue(settings)
    for fix in with_gap(2.0, now - 2.2, now):
        clue.add(fix)
    assert settings.velocity_max_fix_age_s == 6.5
    assert (clue.velocity() is not None) is fits
