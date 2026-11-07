"""Fine-tune the detector on one modality's training clips, then choose its threshold on validation.

The test split is never read here. ``--measure`` only reports speed, so the time budget can be set
before committing to a long run.
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from cuas.config import DetectorSettings, TrainingSettings, load_site
from cuas.hashing import sha256_of
from cuas.media_manifest import MANIFEST_NAME, ClipEntry, load_manifest
from cuas.metrics.mat_labels import read_label_file
from cuas.metrics.recorded_media import ClipScore, add_frame, summarise_video
from cuas.recordings import decode_frames, frame_count
from cuas.station.detector import (
    Box,
    Detector,
    build_model,
    frame_to_tensor,
    load_starting_weights,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
FRAME_CACHE = DATA_DIR / "frames"
MODELS_DIR = ROOT / "models"
STARTING_WEIGHTS = (
    MODELS_DIR / "pretrained" / "ssdlite320_mobilenet_v3_large_coco-a79551df.pth"
)
MEASURE_BATCHES = 8
LOG_EVERY_BATCHES = 25
THRESHOLDS = tuple(round(t, 2) for t in np.arange(0.1, 0.95, 0.05))
MIN_BOX_PX = 1.0


@dataclass(frozen=True)
class Sample:
    clip: ClipEntry
    index: int
    boxes: tuple[Box, ...]


@dataclass(frozen=True)
class Checkpoint:
    """Keeps a long run's progress after each epoch, so a killed process loses one epoch at most."""

    path: Path
    run: str

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        saved = torch.load(self.path)
        if saved["run"] != self.run:
            raise SystemExit(
                f"{self.path} came from other settings. Delete it to start again."
            )
        return saved

    def save(self, state: dict) -> None:
        scratch = self.path.with_suffix(".tmp")
        torch.save({**state, "run": self.run}, scratch)
        scratch.replace(self.path)  # a kill during the write leaves the last good one


def sample_clip(clip: ClipEntry, per_clip: int) -> list[Sample]:
    """Evenly spaced frames, cached on disk so training does not hold them all in memory."""
    count = frame_count(DATA_DIR / clip.path)
    labels = read_label_file(DATA_DIR / clip.labels_path, count)
    indices = sorted({int(i) for i in np.linspace(0, count - 1, per_clip)})
    missing = [i for i in indices if not _cache_path(clip, i).exists()]
    for index, frame in decode_frames(DATA_DIR / clip.path, missing).items():
        np.save(_cache_path(clip, index), frame)
    return [Sample(clip, i, tuple(labels[i])) for i in indices]


def _cache_path(clip: ClipEntry, index: int) -> Path:
    return FRAME_CACHE / f"{clip.id}_{index:04d}.npy"


def load_sample(sample: Sample) -> np.ndarray:
    return np.load(_cache_path(sample.clip, sample.index), mmap_mode="r")


def to_target(
    boxes: tuple[Box, ...],
    classes: tuple[str, ...],
    width: int,
    height: int,
    flip: bool,
) -> dict[str, torch.Tensor]:
    rows, labels = [], []
    for box in boxes:
        x1, x2 = (width - box.x2, width - box.x1) if flip else (box.x1, box.x2)
        x1, y1 = max(x1, 0.0), max(box.y1, 0.0)
        x2, y2 = min(x2, float(width)), min(box.y2, float(height))
        if x2 - x1 >= MIN_BOX_PX and y2 - y1 >= MIN_BOX_PX:
            rows.append((x1, y1, x2, y2))
            labels.append(classes.index(box.class_name) + 1)
    return {
        "boxes": torch.tensor(rows, dtype=torch.float32).reshape(-1, 4),
        "labels": torch.tensor(labels, dtype=torch.int64),
    }


def to_batch(
    samples: list[Sample], classes: tuple[str, ...], rng: np.random.Generator
) -> tuple[list[torch.Tensor], list[dict[str, torch.Tensor]]]:
    images, targets = [], []
    for sample in samples:
        frame = load_sample(sample)
        height, width = frame.shape[:2]
        flip = bool(rng.random() < 0.5)
        pixels = np.array(frame[:, ::-1] if flip else frame)
        images.append(frame_to_tensor(pixels))
        targets.append(to_target(sample.boxes, classes, width, height, flip))
    return images, targets


def freeze_backbone(model: torch.nn.Module) -> None:
    for parameter in model.backbone.parameters():
        parameter.requires_grad_(False)


def set_training_mode(model: torch.nn.Module, frozen: bool) -> None:
    model.train()
    if frozen:
        model.backbone.eval()  # keeps the starting normalisation statistics


def train(
    model: torch.nn.Module,
    samples: list[Sample],
    classes: tuple[str, ...],
    settings: TrainingSettings,
    max_batches: int | None = None,
    checkpoint: Checkpoint | None = None,
) -> dict:
    """Runs until the epochs or the time budget run out, whichever comes first."""
    rng = np.random.default_rng(settings.seed)
    parameters = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(
        parameters, lr=settings.learning_rate, weight_decay=settings.weight_decay
    )
    batches, epochs_done, losses, elapsed = 0, 0, [], 0.0
    if saved := checkpoint.load() if checkpoint else None:
        model.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        rng.bit_generator.state = saved["numpy_rng"]
        torch.set_rng_state(saved["torch_rng"])
        batches, epochs_done = saved["batches"], saved["epochs"]
        losses, elapsed = saved["losses"], saved["seconds"]
        print(f"resuming after epoch {epochs_done}")
    started = time.perf_counter() - elapsed
    deadline = started + settings.max_minutes * 60
    for epoch in range(epochs_done, settings.epochs):
        set_training_mode(model, settings.freeze_backbone)
        order = rng.permutation(len(samples))
        for start in range(0, len(order), settings.batch_size):
            chosen = [samples[i] for i in order[start : start + settings.batch_size]]
            images, targets = to_batch(chosen, classes, rng)
            loss = sum(model(images, targets).values())
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            batches += 1
            losses.append(loss.item())
            if batches % LOG_EVERY_BATCHES == 0:
                recent = float(np.mean(losses[-LOG_EVERY_BATCHES:]))
                minutes = (time.perf_counter() - started) / 60
                print(
                    f"epoch {epoch} batch {batches} loss {recent:.3f} {minutes:.1f} min"
                )
            if time.perf_counter() > deadline or batches == max_batches:
                return _summary(
                    batches, epochs_done, losses, started, stopped_early=True
                )
        epochs_done = epoch + 1
        if checkpoint:
            checkpoint.save(
                {
                    "model": model.state_dict(),
                    "optimizer": optimizer.state_dict(),
                    "numpy_rng": rng.bit_generator.state,
                    "torch_rng": torch.get_rng_state(),
                    "batches": batches,
                    "epochs": epochs_done,
                    "losses": losses,
                    "seconds": time.perf_counter() - started,
                }
            )
    return _summary(batches, epochs_done, losses, started, stopped_early=False)


def _summary(
    batches: int, epochs: int, losses: list[float], started: float, stopped_early: bool
) -> dict:
    seconds = time.perf_counter() - started
    return {
        "batches": batches,
        "epochs_completed": epochs,
        "stopped_early": stopped_early,
        "minutes": seconds / 60,
        "seconds_per_batch": seconds / max(batches, 1),
        "first_loss": losses[0] if losses else None,
        "last_loss": float(np.mean(losses[-LOG_EVERY_BATCHES:])) if losses else None,
    }


def score_at(
    detections: list[tuple[Sample, list[Box]]],
    threshold: float,
    classes: tuple[str, ...],
    iou_hit: float,
    iou_strict: float,
) -> dict:
    scores: dict[str, ClipScore] = {}
    for sample, boxes in detections:
        clip = sample.clip
        score = scores.setdefault(
            clip.id, ClipScore(clip.id, clip.label, clip.group, clip.distance_bin)
        )
        kept = [b for b in boxes if b.score >= threshold]
        add_frame(score, kept, sample.boxes, iou_hit, iou_strict)
    return summarise_video(list(scores.values()), classes)


def choose_threshold(
    detections: list[tuple[Sample, list[Box]]],
    classes: tuple[str, ...],
    iou_hit: float,
    iou_strict: float,
) -> tuple[float, dict]:
    """The threshold with the best drone F1, on validation frames only."""
    best, best_f1, best_summary = THRESHOLDS[0], -1.0, {}
    for threshold in THRESHOLDS:
        summary = score_at(detections, threshold, classes, iou_hit, iou_strict)
        row = summary["classes"]["drone"]
        p, r = row["precision"] or 0.0, row["recall"] or 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        if f1 > best_f1:
            best, best_f1, best_summary = threshold, f1, summary
    return best, best_summary


def build_for_training(settings: DetectorSettings, freeze: bool) -> torch.nn.Module:
    model = build_model(settings)
    load_starting_weights(model, STARTING_WEIGHTS)
    if freeze:
        freeze_backbone(model)
    return model


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--modality", choices=["rgb", "thermal"], required=True)
    parser.add_argument("--measure", action="store_true", help="only report speed")
    args = parser.parse_args()

    ai = load_site(CONFIG_DIR).station_ai
    settings, training = ai.detector, ai.training
    torch.manual_seed(training.seed)
    torch.set_num_threads(settings.threads)
    FRAME_CACHE.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(CONFIG_DIR)
    clips = [c for c in manifest.clips if c.modality == args.modality]
    train_clips = [c for c in clips if c.split == "train"]
    val_clips = [c for c in clips if c.split == "val"]
    assert not any(c.split == "test" for c in train_clips + val_clips)

    print(f"sampling {len(train_clips)} training clips")
    train_samples = [
        s for c in train_clips for s in sample_clip(c, training.train_frames_per_clip)
    ]
    print(f"{len(train_samples)} training frames")
    model = build_for_training(settings, training.freeze_backbone)

    if args.measure:
        result = train(
            model, train_samples, settings.classes, training, MEASURE_BATCHES
        )
        epoch_batches = len(train_samples) / training.batch_size
        print(f"seconds per batch: {result['seconds_per_batch']:.1f}")
        print(
            f"minutes per epoch: {result['seconds_per_batch'] * epoch_batches / 60:.1f}"
        )
        return 0

    MODELS_DIR.mkdir(exist_ok=True)
    checkpoint = Checkpoint(
        MODELS_DIR / f"look_{args.modality}.checkpoint.pt",
        json.dumps(
            {
                "manifest": sha256_of(CONFIG_DIR / MANIFEST_NAME),
                "detector": settings.model_dump(),
                "training": training.model_dump(),
            },
            sort_keys=True,
        ),
    )
    result = train(model, train_samples, settings.classes, training, None, checkpoint)
    print(f"training: {result}")
    weights = MODELS_DIR / f"look_{args.modality}.pt"
    torch.save(model.state_dict(), weights)

    print(f"sampling {len(val_clips)} validation clips")
    val_samples = [
        s for c in val_clips for s in sample_clip(c, training.val_frames_per_clip)
    ]
    detector = Detector(model, settings)
    detections = [(s, detector.detect(np.array(load_sample(s)))) for s in val_samples]
    threshold, summary = choose_threshold(
        detections, settings.classes, ai.evaluation.iou_hit, ai.evaluation.iou_strict
    )
    record = {
        "modality": args.modality,
        "weights_sha256": sha256_of(weights),
        "manifest_sha256": sha256_of(CONFIG_DIR / MANIFEST_NAME),
        "high_score": threshold,
        "training": result,
        "validation": summary,
        "validation_frames": len(val_samples),
    }
    (MODELS_DIR / f"look_{args.modality}.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
    checkpoint.path.unlink(missing_ok=True)
    print(f"validation threshold: {threshold}")
    print(f"validation drone: {summary['classes']['drone']}")
    print(f"validation by bin: {summary['drone_misses_by_bin']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
