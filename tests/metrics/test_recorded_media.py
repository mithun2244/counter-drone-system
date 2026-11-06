import pytest

from cuas.metrics.recorded_media import (
    BANNER,
    ClipScore,
    add_frame,
    iou,
    match_frame,
    ratio,
    render_audio_report,
    render_video_report,
    summarise_audio,
    summarise_video,
    timing_summary,
    wilson_interval,
)
from cuas.station.detector import Box

IOU_HIT, IOU_STRICT = 0.3, 0.5
CLASSES = ("drone", "bird")


def box(
    x1: float, y1: float, x2: float, y2: float, score: float = 0.9, name: str = "drone"
) -> Box:
    return Box(x1, y1, x2, y2, score, name)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (box(0, 0, 10, 10), box(0, 0, 10, 10), 1.0),
        (box(0, 0, 10, 10), box(20, 20, 30, 30), 0.0),
        (box(0, 0, 10, 10), box(10, 0, 20, 10), 0.0),  # touching edges share no area
        (box(0, 0, 10, 10), box(5, 0, 15, 10), 50 / 150),
        (box(0, 0, 4, 4), box(1, 1, 3, 3), 4 / 16),
    ],
)
def test_iou_known_answers(a: Box, b: Box, expected: float) -> None:
    assert iou(a, b) == pytest.approx(expected)


def test_a_matching_box_is_a_hit() -> None:
    hits, false, misses = match_frame([box(0, 0, 10, 10)], [box(0, 0, 10, 10)], IOU_HIT)
    assert (len(hits), len(false), len(misses)) == (1, 0, 0)


def test_a_box_in_the_wrong_place_is_both_false_and_a_miss() -> None:
    hits, false, misses = match_frame(
        [box(50, 50, 60, 60)], [box(0, 0, 10, 10)], IOU_HIT
    )
    assert (len(hits), len(false), len(misses)) == (0, 1, 1)


def test_the_wrong_class_never_counts_as_a_hit() -> None:
    prediction = box(0, 0, 10, 10, name="bird")
    hits, false, misses = match_frame([prediction], [box(0, 0, 10, 10)], IOU_HIT)
    assert (len(hits), len(false), len(misses)) == (0, 1, 1)


def test_one_target_cannot_be_hit_twice() -> None:
    predictions = [box(0, 0, 10, 10, score=0.9), box(0, 0, 10, 10, score=0.8)]
    hits, false, misses = match_frame(predictions, [box(0, 0, 10, 10)], IOU_HIT)
    assert hits == [predictions[0]]
    assert false == [predictions[1]]
    assert misses == []


def test_the_strict_threshold_rejects_a_loose_box() -> None:
    score = ClipScore("c", "drone", "g", "medium")
    add_frame(score, [box(0, 0, 10, 10)], [box(4, 0, 14, 10)], IOU_HIT, IOU_STRICT)
    # IoU is 60 / 140 = 0.43: a hit at 0.3 but not at 0.5.
    assert score.hits["drone"] == 1
    assert score.strict_hits["drone"] == 0
    assert score.strict_false["drone"] == 1
    assert score.strict_misses["drone"] == 1


def test_ratio_handles_nothing_to_divide() -> None:
    assert ratio(1, 2) == 0.5
    assert ratio(0, 0) is None


@pytest.mark.parametrize(
    ("k", "n", "low", "high"),
    [
        (5, 5, 0.5655, 1.0),  # all 5 right still leaves a wide interval
        (0, 10, 0.0, 0.2775),
        (8, 10, 0.4902, 0.9433),
        (50, 100, 0.4038, 0.5962),
    ],
)
def test_wilson_interval_known_answers(k: int, n: int, low: float, high: float) -> None:
    interval = wilson_interval(k, n)
    assert interval is not None
    assert interval == pytest.approx((low, high), abs=0.001)


def test_wilson_interval_needs_a_total() -> None:
    assert wilson_interval(0, 0) is None


def test_timing_summary_known_answers() -> None:
    row = timing_summary([10.0, 20.0, 30.0, 40.0, 50.0])
    assert row == {"count": 5, "mean_ms": 30.0, "p50_ms": 30.0, "p95_ms": 48.0}
    assert timing_summary([]) == {"count": 0}


def scored_clips() -> list[ClipScore]:
    """Two drone clips and a bird clip, with counts checkable by hand."""
    target = box(0, 0, 10, 10)
    near = ClipScore("near", "drone", "g1", "close")
    add_frame(near, [target], [target], IOU_HIT, IOU_STRICT)
    add_frame(near, [target], [target], IOU_HIT, IOU_STRICT)
    near.confirmed_tracks["drone"] = 1
    near.first_confirmed_s = 1.0
    far = ClipScore("far", "drone", "g2", "distant")
    add_frame(far, [], [target], IOU_HIT, IOU_STRICT)
    add_frame(far, [box(50, 50, 60, 60)], [], IOU_HIT, IOU_STRICT)
    bird = ClipScore("bird", "bird", "g3", "medium")
    add_frame(
        bird, [box(0, 0, 10, 10)], [box(0, 0, 10, 10, name="bird")], IOU_HIT, IOU_STRICT
    )
    bird.confirmed_tracks["drone"] = 1
    return [near, far, bird]


def test_video_summary_per_class_counts() -> None:
    rows = summarise_video(scored_clips(), CLASSES)["classes"]
    drone = rows["drone"]
    assert (drone["hits"], drone["false_detections"], drone["misses"]) == (2, 2, 1)
    assert drone["precision"] == pytest.approx(0.5)
    assert drone["recall"] == pytest.approx(2 / 3)
    assert (rows["bird"]["hits"], rows["bird"]["misses"]) == (0, 1)


def test_video_summary_separates_kinds_of_false_detection() -> None:
    false = summarise_video(scored_clips(), CLASSES)["false_detections"]
    assert false["frames"] == 5
    assert false["total"] == 2
    assert false["per_1000_frames"] == pytest.approx(400.0)
    assert false["drone_box_on_other_class_clip"] == 1
    assert false["box_on_frame_with_no_target"] == 1


def test_video_summary_misses_by_distance_bin() -> None:
    bins = summarise_video(scored_clips(), CLASSES)["drone_misses_by_bin"]
    assert bins["close"]["miss_rate"] == 0.0
    assert bins["close"]["clips_confirmed"] == 1
    assert bins["distant"]["miss_rate"] == 1.0
    assert bins["distant"]["clips_confirmed"] == 0


def test_video_summary_clip_level_counts_scene_groups() -> None:
    clip = summarise_video(scored_clips(), CLASSES)["clip_level"]
    assert clip["drone_clips"] == 2
    assert clip["drone_clips_confirmed"] == 1
    assert clip["other_clips_with_false_drone_track"] == 1
    assert clip["median_time_to_confirm_s"] == 1.0
    assert clip["scene_groups"] == 3
    assert clip["drone_scene_groups"] == 2


def test_audio_summary_known_answers() -> None:
    labels = ("electric_drone", "background")
    results = [
        ("electric_drone", "electric_drone"),
        ("electric_drone", "electric_drone"),
        ("electric_drone", "electric_drone"),
        ("electric_drone", "background"),
        ("background", "background"),
        ("background", "electric_drone"),
    ]
    row = summarise_audio(results, labels, "background")
    assert row["clips"] == 6
    assert row["accuracy"] == pytest.approx(4 / 6)
    assert row["majority_baseline"] == pytest.approx(4 / 6)
    assert row["misses"] == 1
    assert row["false_detections"] == 1
    assert row["per_class"]["electric_drone"]["precision"] == pytest.approx(3 / 4)
    assert row["per_class"]["electric_drone"]["recall"] == pytest.approx(3 / 4)


def test_video_report_is_labelled_and_never_looks_like_a_simulator_result() -> None:
    summary = summarise_video(scored_clips(), CLASSES)
    report = render_video_report(
        "look_rgb",
        summary,
        {"Weights SHA-256": "abc", "Test evaluations so far": 1},
        {"inference": timing_summary([10.0, 20.0])},
    )
    assert report.startswith(f"# {BANNER}")
    assert "[evaluator]" not in report
    assert "simulator results" not in report
    assert "Weights SHA-256" in report
    for heading in ("Misses", "False detections", "CPU time", "Clip level"):
        assert heading.lower() in report.lower()
    assert "2 scene groups" in report


def test_audio_report_is_labelled_and_carries_its_notes() -> None:
    labels = ("electric_drone", "background")
    row = summarise_audio([("background", "background")], labels, "background")
    report = render_audio_report(
        "sound",
        {"clean": row},
        {"Weights SHA-256": "abc"},
        {},
        notes=["Engine is a proxy."],
    )
    assert report.startswith(f"# {BANNER}")
    assert "Engine is a proxy." in report
    assert "[evaluator]" not in report
