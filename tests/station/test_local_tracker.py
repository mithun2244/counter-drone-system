import pytest

from cuas.station.detector import Box
from cuas.station.local_tracker import LocalTracker, centre

HIGH = 0.5
MAX_STEP = 20.0
MAX_MISSED = 2


def tracker() -> LocalTracker:
    return LocalTracker(HIGH, MAX_STEP, MAX_MISSED)


def box(x: float, y: float = 0.0, score: float = 0.9, name: str = "drone") -> Box:
    return Box(x - 1, y - 1, x + 1, y + 1, score, name)


def test_centre_is_the_middle_of_the_box() -> None:
    assert centre(Box(0, 2, 4, 10, 0.9, "drone")) == (2.0, 6.0)


def test_a_high_score_box_starts_a_track() -> None:
    t = tracker()
    seen = t.update([box(10)])
    assert [track.track_id for track in seen] == [1]
    assert t.tracks[0].position == (10.0, 0.0)


def test_a_low_score_box_cannot_start_a_track() -> None:
    t = tracker()
    assert t.update([box(10, score=0.2)]) == []
    assert t.tracks == []


def test_a_moving_target_keeps_its_id() -> None:
    t = tracker()
    for x in (0, 10, 20, 30):
        t.update([box(x)])
    assert [track.track_id for track in t.tracks] == [1]
    assert t.tracks[0].velocity == (10.0, 0.0)


def test_a_low_score_box_continues_an_existing_track() -> None:
    t = tracker()
    t.update([box(0)])
    seen = t.update([box(5, score=0.2)])
    assert [track.track_id for track in seen] == [1]
    assert t.tracks[0].missed == 0


def test_high_score_boxes_are_matched_before_low_score_ones() -> None:
    t = tracker()
    t.update([box(0)])
    t.update([box(1, score=0.2), box(3, score=0.9)])
    assert t.tracks[0].position == (3.0, 0.0)


def test_two_targets_are_kept_apart_by_position() -> None:
    t = tracker()
    t.update([box(0), box(100)])
    t.update([box(102), box(2)])
    positions = {track.track_id: track.position[0] for track in t.tracks}
    assert positions == {1: 2.0, 2: 102.0}


def test_a_box_too_far_away_starts_a_new_track() -> None:
    t = tracker()
    t.update([box(0)])
    t.update([box(MAX_STEP + 1)])
    assert [track.track_id for track in t.tracks] == [1, 2]


def test_a_missed_track_continues_along_its_velocity() -> None:
    t = tracker()
    t.update([box(0)])
    t.update([box(10)])
    t.update([])
    assert t.tracks[0].predicted() == (30.0, 0.0)
    t.update([box(30)])
    assert [track.track_id for track in t.tracks] == [1]
    assert t.tracks[0].history == [(0.0, 0.0), (10.0, 0.0), None, (30.0, 0.0)]


def test_a_track_is_dropped_after_too_many_misses() -> None:
    t = tracker()
    t.update([box(0)])
    for _ in range(MAX_MISSED):
        t.update([])
    assert len(t.tracks) == 1
    t.update([])
    assert t.tracks == []


def test_confidence_is_the_average_score_per_class() -> None:
    t = tracker()
    t.update([box(0, score=0.8)])
    t.update([box(1, score=0.6)])
    t.update([box(2, score=0.9, name="bird")])
    assert t.tracks[0].confidence() == pytest.approx({"drone": 0.7, "bird": 0.9})
