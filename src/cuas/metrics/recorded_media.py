"""Scores the models on recorded media, using the dataset's labels.

These are never simulator results. This module and ``cuas.metrics.evaluator`` cannot import each
other, and their numbers are never combined.
"""

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np

from cuas.station.detector import Box

BANNER = "RECORDED MEDIA, HELD-OUT SPLIT"
NOT_SIMULATOR = "These numbers come from recorded clips, not from the simulator."
DRONE = "drone"
WILSON_Z_95 = 1.959964
PER_THOUSAND = 1000.0


def iou(a: Box, b: Box) -> float:
    width = min(a.x2, b.x2) - max(a.x1, b.x1)
    height = min(a.y2, b.y2) - max(a.y1, b.y1)
    if width <= 0 or height <= 0:
        return 0.0
    overlap = width * height
    area_a = (a.x2 - a.x1) * (a.y2 - a.y1)
    area_b = (b.x2 - b.x1) * (b.y2 - b.y1)
    return overlap / (area_a + area_b - overlap)


def match_frame(
    predictions: Sequence[Box], truths: Sequence[Box], threshold: float
) -> tuple[list[Box], list[Box], list[Box]]:
    """Hits, false detections and misses. Best-scoring boxes choose first; classes must match."""
    open_truths = list(truths)
    hits, false = [], []
    for box in sorted(predictions, key=lambda b: -b.score):
        candidates = [t for t in open_truths if t.class_name == box.class_name]
        best = max(candidates, key=lambda t: iou(box, t), default=None)
        if best is not None and iou(box, best) >= threshold:
            hits.append(box)
            open_truths.remove(best)
        else:
            false.append(box)
    return hits, false, open_truths


def ratio(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def wilson_interval(successes: int, total: int) -> tuple[float, float] | None:
    """95% interval for a proportion. It stays honest for small counts and rates near 0 or 1."""
    if total == 0:
        return None
    z = WILSON_Z_95
    p = successes / total
    denominator = 1 + z**2 / total
    middle = (p + z**2 / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / denominator
    return max(0.0, middle - margin), min(1.0, middle + margin)


def timing_summary(milliseconds: Iterable[float]) -> dict[str, float | int]:
    values = np.array(list(milliseconds), dtype=float)
    if not values.size:
        return {"count": 0}
    return {
        "count": int(values.size),
        "mean_ms": float(values.mean()),
        "p50_ms": float(np.percentile(values, 50)),
        "p95_ms": float(np.percentile(values, 95)),
    }


@dataclass
class ClipScore:
    """Everything counted for one held-out video clip."""

    clip_id: str
    label: str
    group: str
    distance_bin: str | None
    frames: int = 0
    hits: Counter[str] = field(default_factory=Counter)
    false: Counter[str] = field(default_factory=Counter)
    misses: Counter[str] = field(default_factory=Counter)
    strict_hits: Counter[str] = field(default_factory=Counter)
    strict_false: Counter[str] = field(default_factory=Counter)
    strict_misses: Counter[str] = field(default_factory=Counter)
    false_on_empty_frames: int = 0
    confirmed_tracks: Counter[str] = field(default_factory=Counter)
    first_confirmed_s: float | None = None


def add_frame(
    score: ClipScore,
    predictions: Sequence[Box],
    truths: Sequence[Box],
    iou_hit: float,
    iou_strict: float,
) -> None:
    score.frames += 1
    hits, false, misses = match_frame(predictions, truths, iou_hit)
    score.hits.update(b.class_name for b in hits)
    score.false.update(b.class_name for b in false)
    score.misses.update(b.class_name for b in misses)
    if not truths:
        score.false_on_empty_frames += len(false)
    hits, false, misses = match_frame(predictions, truths, iou_strict)
    score.strict_hits.update(b.class_name for b in hits)
    score.strict_false.update(b.class_name for b in false)
    score.strict_misses.update(b.class_name for b in misses)


def _totals(clips: Sequence[ClipScore], attribute: str) -> Counter[str]:
    total: Counter[str] = Counter()
    for clip in clips:
        total.update(getattr(clip, attribute))
    return total


def _class_rows(clips: Sequence[ClipScore], classes: Sequence[str]) -> dict[str, dict]:
    rows = {}
    for name in classes:
        hits = _totals(clips, "hits")[name]
        false = _totals(clips, "false")[name]
        misses = _totals(clips, "misses")[name]
        strict_hits = _totals(clips, "strict_hits")[name]
        rows[name] = {
            "hits": hits,
            "false_detections": false,
            "misses": misses,
            "precision": ratio(hits, hits + false),
            "recall": ratio(hits, hits + misses),
            "precision_strict": ratio(
                strict_hits, strict_hits + _totals(clips, "strict_false")[name]
            ),
            "recall_strict": ratio(
                strict_hits, strict_hits + _totals(clips, "strict_misses")[name]
            ),
        }
    return rows


def _misses_by_bin(clips: Sequence[ClipScore]) -> dict[str, dict]:
    """Drone misses per distance bin, because small distant targets are the known weakness."""
    bins: defaultdict[str, list[ClipScore]] = defaultdict(list)
    for clip in clips:
        if clip.label == DRONE and clip.distance_bin:
            bins[clip.distance_bin].append(clip)
    rows = {}
    for name, members in sorted(bins.items()):
        hits = sum(c.hits[DRONE] for c in members)
        misses = sum(c.misses[DRONE] for c in members)
        confirmed = sum(c.confirmed_tracks[DRONE] > 0 for c in members)
        rows[name] = {
            "clips": len(members),
            "misses": misses,
            "miss_rate": ratio(misses, hits + misses),
            "clips_confirmed": confirmed,
            "clips_confirmed_interval": wilson_interval(confirmed, len(members)),
        }
    return rows


def _false_detections(clips: Sequence[ClipScore]) -> dict:
    frames = sum(c.frames for c in clips)
    total = sum(sum(c.false.values()) for c in clips)
    on_others = sum(c.false[DRONE] for c in clips if c.label != DRONE)
    empty = sum(c.false_on_empty_frames for c in clips)
    per_thousand = None if not frames else total / frames * PER_THOUSAND
    return {
        "frames": frames,
        "total": total,
        "per_1000_frames": per_thousand,
        "drone_box_on_other_class_clip": on_others,
        "box_on_frame_with_no_target": empty,
    }


def _clip_level(clips: Sequence[ClipScore]) -> dict:
    drones = [c for c in clips if c.label == DRONE]
    others = [c for c in clips if c.label != DRONE]
    confirmed = sum(c.confirmed_tracks[DRONE] > 0 for c in drones)
    false_clips = sum(c.confirmed_tracks[DRONE] > 0 for c in others)
    times = [c.first_confirmed_s for c in drones if c.first_confirmed_s is not None]
    return {
        "drone_clips": len(drones),
        "drone_clips_confirmed": confirmed,
        "drone_clips_confirmed_interval": wilson_interval(confirmed, len(drones)),
        "other_clips": len(others),
        "other_clips_with_false_drone_track": false_clips,
        "other_clips_false_interval": wilson_interval(false_clips, len(others)),
        "median_time_to_confirm_s": float(np.median(times)) if times else None,
        "scene_groups": len({c.group for c in clips}),
        "drone_scene_groups": len({c.group for c in drones}),
    }


def summarise_video(clips: Sequence[ClipScore], classes: Sequence[str]) -> dict:
    return {
        "classes": _class_rows(clips, classes),
        "drone_misses_by_bin": _misses_by_bin(clips),
        "false_detections": _false_detections(clips),
        "clip_level": _clip_level(clips),
        "worst_drone_clips": _worst_clips(clips),
    }


def _worst_clips(clips: Sequence[ClipScore], count: int = 5) -> list[dict]:
    drones = [c for c in clips if c.label == DRONE]
    ranked = sorted(drones, key=lambda c: (-c.misses[DRONE], c.clip_id))[:count]
    return [
        {"clip_id": c.clip_id, "misses": c.misses[DRONE], "frames": c.frames}
        for c in ranked
    ]


def summarise_audio(
    results: Sequence[tuple[str, str]], labels: Sequence[str], negative: str
) -> dict:
    """``results`` are (true label, predicted label) per clip."""
    confusion = {t: dict.fromkeys(labels, 0) for t in labels}
    for true, predicted in results:
        confusion[true][predicted] += 1
    total = len(results)
    correct = sum(confusion[name][name] for name in labels)
    per_class = {}
    for name in labels:
        hits = confusion[name][name]
        predicted = sum(confusion[t][name] for t in labels)
        actual = sum(confusion[name].values())
        per_class[name] = {
            "clips": actual,
            "precision": ratio(hits, predicted),
            "recall": ratio(hits, actual),
        }
    biggest = max((sum(row.values()) for row in confusion.values()), default=0)
    return {
        "clips": total,
        "accuracy": ratio(correct, total),
        "accuracy_interval": wilson_interval(correct, total),
        "majority_baseline": ratio(biggest, total),
        "confusion": confusion,
        "per_class": per_class,
        "misses": sum(confusion[t][negative] for t in labels if t != negative),
        "false_detections": sum(
            confusion[negative][p] for p in labels if p != negative
        ),
    }


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _fmt_interval(interval: tuple[float, float] | None) -> str:
    return "n/a" if interval is None else f"{interval[0]:.3f} to {interval[1]:.3f}"


def _header(title: str, provenance: dict) -> list[str]:
    lines = [f"# {BANNER}: {title}", "", NOT_SIMULATOR, ""]
    lines += [f"- **{key}:** {value}" for key, value in provenance.items()]
    return [*lines, ""]


def _timing_lines(timing: dict[str, dict]) -> list[str]:
    lines = ["## CPU time", "", "| Stage | Count | Mean ms | p50 ms | p95 ms |"]
    lines.append("| --- | --- | --- | --- | --- |")
    for stage, row in timing.items():
        if not row.get("count"):
            lines.append(f"| {stage} | 0 | n/a | n/a | n/a |")
            continue
        lines.append(
            f"| {stage} | {row['count']} | {row['mean_ms']:.1f} | "
            f"{row['p50_ms']:.1f} | {row['p95_ms']:.1f} |"
        )
    return [*lines, ""]


def render_video_report(
    title: str, summary: dict, provenance: dict, timing: dict[str, dict]
) -> str:
    lines = _header(title, provenance)
    clip = summary["clip_level"]
    lines += [
        "## Clip level, after M-of-N confirmation",
        "",
        (
            f"Intervals treat clips as independent, but the {clip['drone_clips']} drone clips "
            f"come from only {clip['drone_scene_groups']} scene groups, so true uncertainty is wider."
        ),
        "",
        (
            f"- Drone clips confirmed: {clip['drone_clips_confirmed']} of {clip['drone_clips']} "
            f"(95% interval {_fmt_interval(clip['drone_clips_confirmed_interval'])})"
        ),
        (
            f"- Other clips with a false drone track: {clip['other_clips_with_false_drone_track']} "
            f"of {clip['other_clips']} (95% interval {_fmt_interval(clip['other_clips_false_interval'])})"
        ),
        f"- Median time to confirm: {_fmt(clip['median_time_to_confirm_s'])} s",
        "",
        "## Frame level, per class",
        "",
        (
            "| Class | Hits | False detections | Misses | Precision | Recall | "
            "Precision (strict) | Recall (strict) |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, row in summary["classes"].items():
        lines.append(
            f"| {name} | {row['hits']} | {row['false_detections']} | {row['misses']} | "
            f"{_fmt(row['precision'])} | {_fmt(row['recall'])} | "
            f"{_fmt(row['precision_strict'])} | {_fmt(row['recall_strict'])} |"
        )
    lines += ["", "## Drone misses by distance bin", ""]
    lines += ["| Bin | Clips | Misses | Miss rate | Clips confirmed | 95% interval |"]
    lines += ["| --- | --- | --- | --- | --- | --- |"]
    for name, row in summary["drone_misses_by_bin"].items():
        lines.append(
            f"| {name} | {row['clips']} | {row['misses']} | {_fmt(row['miss_rate'])} | "
            f"{row['clips_confirmed']} | {_fmt_interval(row['clips_confirmed_interval'])} |"
        )
    false = summary["false_detections"]
    lines += [
        "",
        "## False detections",
        "",
        (
            f"- Total: {false['total']} in {false['frames']} frames "
            f"({_fmt(false['per_1000_frames'])} per 1,000 frames)"
        ),
        (
            f"- Drone box on a bird, airplane or helicopter clip: "
            f"{false['drone_box_on_other_class_clip']}"
        ),
        f"- Any box on a frame with no target: {false['box_on_frame_with_no_target']}",
        "",
        "## Worst drone clips",
        "",
    ]
    lines += [
        f"- `{row['clip_id']}`: {row['misses']} misses in {row['frames']} frames"
        for row in summary["worst_drone_clips"]
    ]
    return "\n".join([*lines, "", *_timing_lines(timing)])


def render_audio_report(
    title: str,
    summaries: dict[str, dict],
    provenance: dict,
    timing: dict[str, dict],
    notes: Sequence[str] = (),
) -> str:
    lines = _header(title, provenance)
    lines += [*notes, ""] if notes else []
    lines += [
        "## By condition",
        "",
        (
            "| Condition | Clips | Accuracy | 95% interval | Majority baseline | "
            "Misses | False detections |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for condition, row in summaries.items():
        lines.append(
            f"| {condition} | {row['clips']} | {_fmt(row['accuracy'])} | "
            f"{_fmt_interval(row['accuracy_interval'])} | "
            f"{_fmt(row['majority_baseline'])} | {row['misses']} | "
            f"{row['false_detections']} |"
        )
    for condition, row in summaries.items():
        lines += ["", f"## Confusion: {condition}", ""]
        labels = list(row["confusion"])
        lines.append("| True \\ Predicted | " + " | ".join(labels) + " |")
        lines.append("| --- |" + " --- |" * len(labels))
        for true in labels:
            cells = " | ".join(str(row["confusion"][true][p]) for p in labels)
            lines.append(f"| {true} | {cells} |")
    return "\n".join([*lines, "", *_timing_lines(timing)])
