import pytest

from cuas.station.confirm import is_confirmed

M, N, MAX_STEP = 3, 5, 10.0
HIT = (0.0, 0.0)


def points(*marks: int) -> list[tuple[float, float] | None]:
    """A straight, slow path, where 1 means seen and 0 means missed."""
    return [(float(i), 0.0) if mark else None for i, mark in enumerate(marks)]


@pytest.mark.parametrize(
    ("marks", "expected"),
    [
        ((1,), False),
        ((1, 1), False),
        ((1, 1, 1), True),
        ((1, 0, 1, 0, 1), True),
        ((1, 0, 0, 1, 1), True),
        ((1, 0, 0, 0, 1), False),
        ((0, 0, 0, 0, 0), False),
    ],
    ids=str,
)
def test_three_of_five_truth_table(marks: tuple[int, ...], expected: bool) -> None:
    assert is_confirmed(points(*marks), M, N, MAX_STEP) is expected


def test_only_the_last_n_frames_count() -> None:
    assert is_confirmed(points(1, 1, 1, 0, 0, 0, 0, 0), M, N, MAX_STEP) is False
    assert is_confirmed(points(0, 0, 0, 1, 1, 1, 0, 0), M, N, MAX_STEP) is True


def test_a_jump_is_not_a_smooth_path() -> None:
    history = [(0.0, 0.0), (5.0, 0.0), (5.0 + MAX_STEP + 1, 0.0)]
    assert is_confirmed(history, M, N, MAX_STEP) is False


def test_a_missed_frame_allows_a_proportionally_longer_step() -> None:
    history = [(0.0, 0.0), (5.0, 0.0), None, (5.0 + MAX_STEP * 2, 0.0)]
    assert is_confirmed(history, M, N, MAX_STEP) is True
    history[-1] = (5.0 + MAX_STEP * 2 + 1, 0.0)
    assert is_confirmed(history, M, N, MAX_STEP) is False


def test_a_track_that_stays_still_is_smooth() -> None:
    assert is_confirmed([HIT, HIT, HIT], M, N, MAX_STEP) is True
