"""The hybrid link: a simulated detection pulls a recorded clip and runs a real model on it.

This is the only place truth meets recordings. The true target type and range choose a held-out
clip, and the model then sees pixels only, so its answer cannot depend on the truth.
"""

import json
import math
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from cuas.config import DetectorSettings, LookSettings, StationAiSettings, TargetType
from cuas.media_manifest import ClipEntry, load_manifest
from cuas.recordings import decode_every, frame_rate
from cuas.schemas import SensorKind
from cuas.sim.rng import stream
from cuas.sim.station import Look
from cuas.station.detector import load_trained
from cuas.station.look import CachedDetector, LookStream

# No fixed-wing drone is in the footage, so an attack drone has no clips and no real look.
CAMERA_LABELS: Mapping[TargetType, str] = {
    "quadcopter": "drone",
    "friendly_drone": "drone",
    "bird": "bird",
}
BINS_NEAREST_FIRST = ("close", "medium", "distant")
HELD_OUT = "test"


@dataclass(frozen=True)
class LookModel:
    detector: CachedDetector
    classes: tuple[str, ...]
    high_score: float


@dataclass
class _Stream:
    clip: ClipEntry
    distance_bin: str
    frames: list[np.ndarray]
    position: int
    look: LookStream
    next_tick: int
    result: Look | None = None


def distance_bin(range_m: float, limits: tuple[float, float]) -> str:
    close, medium = limits
    if range_m < close:
        return "close"
    return "medium" if range_m < medium else "distant"


class MediaLink:
    """Supplies real look evidence for simulated detections. Held-out clips only."""

    def __init__(
        self,
        clips: Sequence[ClipEntry],
        load_frames: Callable[[ClipEntry], list[np.ndarray]],
        models: Mapping[SensorKind, LookModel],
        settings: LookSettings,
        tick_s: float,
        seed: int,
    ) -> None:
        self._load_frames = load_frames
        self._models = models
        self._settings = settings
        self._tick_s = tick_s
        self._seed = seed
        self._look_every_ticks = round(settings.period_s / tick_s)
        if not math.isclose(self._look_every_ticks * tick_s, settings.period_s):
            raise ValueError(
                f"look period {settings.period_s} s is not a whole number of "
                f"{tick_s} s ticks"
            )
        self._clips: defaultdict[tuple[str, str, str | None], list[ClipEntry]] = (
            defaultdict(list)
        )
        for clip in sorted(clips, key=lambda c: c.id):
            if clip.split == HELD_OUT:
                self._clips[(clip.modality, clip.label, clip.distance_bin)].append(clip)
        self._frames: dict[str, list[np.ndarray]] = {}
        self._streams: dict[tuple[str, str, str], _Stream] = {}

    def look(
        self,
        station_id: str,
        sensor: SensorKind,
        target_id: str,
        target_type: TargetType,
        range_m: float,
        t: float,
    ) -> Look | None:
        """What the model reports for this detection, or ``None`` if no clip can stand in."""
        label = CAMERA_LABELS.get(target_type)
        model = self._models.get(sensor)
        if label is None or model is None:
            return None
        tick = round(t / self._tick_s)
        key = (station_id, sensor, target_id)
        wanted = distance_bin(range_m, self._settings.range_bins_m[label])
        state = self._streams.get(key)
        if state is None or state.distance_bin != wanted:
            state = self._open(key, sensor, label, wanted, model, tick)
            self._streams[key] = state
        if tick >= state.next_tick:
            self._advance(state, model, tick)
        return state.result

    def _open(
        self,
        key: tuple[str, str, str],
        sensor: SensorKind,
        label: str,
        wanted: str,
        model: LookModel,
        tick: int,
    ) -> _Stream:
        clips = self._candidates(sensor, label, wanted)
        rng = stream(self._seed, "clip", *key, wanted)
        clip = clips[int(rng.integers(len(clips)))]
        if clip.id not in self._frames:
            self._frames[clip.id] = self._load_frames(clip)
        frames = self._frames[clip.id]
        width = frames[0].shape[1]
        look = LookStream(self._settings, model.classes, model.high_score, width)
        return _Stream(clip, wanted, frames, int(rng.integers(len(frames))), look, tick)

    def _candidates(self, sensor: str, label: str, wanted: str) -> list[ClipEntry]:
        """Clips in the wanted bin, or else the nearest bin that has any."""
        start = BINS_NEAREST_FIRST.index(wanted)
        order = sorted(
            BINS_NEAREST_FIRST, key=lambda b: abs(BINS_NEAREST_FIRST.index(b) - start)
        )
        for candidate in order:
            if clips := self._clips[(sensor, label, candidate)]:
                return clips
        raise ValueError(f"no held-out {sensor} clips for {label}")

    def _advance(self, state: _Stream, model: LookModel, tick: int) -> None:
        index = state.position % len(state.frames)
        frame_key = f"{state.clip.id}:{index}"
        boxes = model.detector.boxes(frame_key, state.frames[index])
        state.result = Look(state.look.update(boxes), frame_key)
        state.position += 1
        state.next_tick = tick + self._look_every_ticks


def load_look_models(
    models_dir: Path, settings: DetectorSettings
) -> dict[SensorKind, LookModel]:
    """Each camera's trained model. A camera with no trained model has no real look."""
    models: dict[SensorKind, LookModel] = {}
    sensors: tuple[SensorKind, ...] = ("rgb", "thermal")
    for sensor in sensors:
        weights = models_dir / f"look_{sensor}.pt"
        if not weights.exists():
            continue
        record = json.loads(
            (models_dir / f"look_{sensor}.json").read_text(encoding="utf-8")
        )
        detector = load_trained(settings, weights)
        models[sensor] = LookModel(
            CachedDetector(detector.detect), settings.classes, record["high_score"]
        )
    return models


def clip_frames(
    data_dir: Path, period_s: float
) -> Callable[[ClipEntry], list[np.ndarray]]:
    """Reads a clip at the look rate, so every frame kept gets used."""

    def load(clip: ClipEntry) -> list[np.ndarray]:
        path = data_dir / clip.path
        return decode_every(path, round(period_s * frame_rate(path)))

    return load


def build_media_link(
    config_dir: Path,
    data_dir: Path,
    models_dir: Path,
    ai: StationAiSettings,
    tick_s: float,
    seed: int,
) -> MediaLink:
    models = load_look_models(models_dir, ai.detector)
    if not models:
        raise FileNotFoundError(f"no trained models in {models_dir}")
    return MediaLink(
        load_manifest(config_dir).clips,
        clip_frames(data_dir, ai.look.period_s),
        models,
        ai.look,
        tick_s,
        seed,
    )
