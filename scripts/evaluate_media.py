"""Score a trained model on recorded clips. Writes runs/eval/<model>/report.md and metrics.json.

These are recorded-media results, never simulator results. Every run on the test split is logged
with its weights hash, and the report shows how many times those weights have seen that split.
"""

import argparse
import json
import platform
import sys
import time
from pathlib import Path

import torch

from cuas.config import StationAiSettings, load_site
from cuas.hashing import sha256_of
from cuas.media_manifest import MANIFEST_NAME, ClipEntry, load_manifest
from cuas.metrics.mat_labels import read_label_file
from cuas.metrics.recorded_media import (
    ClipScore,
    add_frame,
    render_video_report,
    summarise_video,
    timing_summary,
)
from cuas.recordings import decode_frames, frame_count, frame_rate
from cuas.station.detector import Detector, load_trained
from cuas.station.look import LookStream

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
MODELS_DIR = ROOT / "models"
EVAL_DIR = ROOT / "runs" / "eval"
ATTEMPTS_LOG = EVAL_DIR / "attempts.jsonl"
FRAME_STEP = 5  # neighbouring frames are near-copies, so every 5th frame is enough
MIN_TIMING_FRAMES = 1000
TO_MS = 1000.0


def count_attempts(model: str, split: str, weights: str) -> int:
    """Log this run and return how many times these weights have seen this split."""
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    entry = {"model": model, "split": split, "weights_sha256": weights}
    with ATTEMPTS_LOG.open("a", encoding="utf-8") as log:
        log.write(json.dumps(entry) + "\n")
    lines = ATTEMPTS_LOG.read_text(encoding="utf-8").splitlines()
    return sum(json.loads(line) == entry for line in lines)


def score_clip(
    clip: ClipEntry,
    detector: Detector,
    ai: StationAiSettings,
    high_score: float,
    timing: dict[str, list[float]],
) -> ClipScore:
    """Frame-level scores on every 5th frame, and M-of-N at the rate the demo looks."""
    path = DATA_DIR / clip.path
    count = frame_count(path)
    labels = read_label_file(DATA_DIR / clip.labels_path, count)
    rate = frame_rate(path)
    look_step = round(ai.look.period_s * rate)
    indices = sorted(set(range(0, count, FRAME_STEP)) | set(range(0, count, look_step)))
    started = time.perf_counter()
    frames = decode_frames(path, indices)
    timing["decode"].append((time.perf_counter() - started) / len(frames) * TO_MS)

    width = next(iter(frames.values())).shape[1]
    stream = LookStream(ai.look, ai.detector.classes, high_score, width)
    score = ClipScore(clip.id, clip.label, clip.group, clip.distance_bin)
    for index in indices:
        started = time.perf_counter()
        boxes = detector.detect(frames[index])
        timing["inference"].append((time.perf_counter() - started) * TO_MS)
        if index % FRAME_STEP == 0:
            kept = [b for b in boxes if b.score >= high_score]
            add_frame(
                score,
                kept,
                labels[index],
                ai.evaluation.iou_hit,
                ai.evaluation.iou_strict,
            )
        if index % look_step == 0:
            started = time.perf_counter()
            result = stream.update(boxes)
            timing["tracker"].append((time.perf_counter() - started) * TO_MS)
            _note_confirmed(score, result, clip.label, index / rate)
    return score


def _note_confirmed(
    score: ClipScore, result: dict[str, float], label: str, seconds: float
) -> None:
    for name, confidence in result.items():
        if confidence > 0.0:
            score.confirmed_tracks[name] = 1
            if name == label and score.first_confirmed_s is None:
                score.first_confirmed_s = seconds


def single_thread_timing(clips: list[ClipEntry], detector: Detector) -> list[float]:
    """Inference time on one thread, the case for a machine with little CPU to spare."""
    torch.set_num_threads(1)
    times: list[float] = []
    for clip in clips:
        path = DATA_DIR / clip.path
        indices = range(0, frame_count(path), FRAME_STEP)
        for frame in decode_frames(path, indices).values():
            started = time.perf_counter()
            detector.detect(frame)
            times.append((time.perf_counter() - started) * TO_MS)
            if len(times) >= MIN_TIMING_FRAMES:
                return times
    return times


def evaluate_video(modality: str, split: str, ai: StationAiSettings) -> dict:
    name = f"look_{modality}"
    weights = MODELS_DIR / f"{name}.pt"
    record = json.loads((MODELS_DIR / f"{name}.json").read_text(encoding="utf-8"))
    manifest = load_manifest(CONFIG_DIR)
    manifest_hash = sha256_of(CONFIG_DIR / MANIFEST_NAME)
    if record["manifest_sha256"] != manifest_hash:
        raise SystemExit("these weights were trained against a different manifest")
    clips = [c for c in manifest.clips if c.modality == modality and c.split == split]
    detector = load_trained(ai.detector, weights)
    high_score = record["high_score"]
    timing: dict[str, list[float]] = {"decode": [], "inference": [], "tracker": []}
    scores = []
    for position, clip in enumerate(clips, start=1):
        scores.append(score_clip(clip, detector, ai, high_score, timing))
        print(f"{position}/{len(clips)} clips", flush=True)
    summary = summarise_video(scores, ai.detector.classes)
    thread_times = single_thread_timing(clips, detector)
    timing_rows = {
        "decode, per frame": timing_summary(timing["decode"]),
        f"inference, {ai.detector.threads} threads": timing_summary(
            timing["inference"]
        ),
        "inference, 1 thread": timing_summary(thread_times),
        "tracker and M-of-N, per look": timing_summary(timing["tracker"]),
    }
    digest = sha256_of(weights)
    provenance = {
        "Split": split,
        "Modality": modality,
        "Frames scored": "every 5th frame of each clip",
        "M-of-N rate": f"one look every {ai.look.period_s} s",
        "Weights SHA-256": digest,
        "Manifest SHA-256": manifest_hash,
        "Threshold, chosen on validation": high_score,
        f"Evaluations of these weights on {split}": count_attempts(name, split, digest),
        "CPU": platform.processor() or platform.machine(),
        "Torch": torch.__version__,
    }
    return {
        "name": name,
        "summary": summary,
        "provenance": provenance,
        "timing": timing_rows,
    }


def write_report(result: dict, split: str, title: str, report: str) -> Path:
    folder = EVAL_DIR / (
        result["name"] if split == "test" else f"{result['name']}_{split}"
    )
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.md").write_text(report, encoding="utf-8")
    metrics = {k: result[k] for k in ("summary", "provenance", "timing")}
    (folder / "metrics.json").write_text(
        json.dumps(metrics, indent=2, default=list), encoding="utf-8"
    )
    return folder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", choices=["look_rgb", "look_thermal"], required=True)
    parser.add_argument("--split", choices=["val", "test"], default="test")
    args = parser.parse_args()
    ai = load_site(CONFIG_DIR).station_ai
    result = evaluate_video(args.model.removeprefix("look_"), args.split, ai)
    report = render_video_report(
        args.model, result["summary"], result["provenance"], result["timing"]
    )
    folder = write_report(result, args.split, args.model, report)
    print(f"wrote {folder / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
