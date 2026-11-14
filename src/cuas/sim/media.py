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
from cuas.recordings import decode_every, frame_rate, read_wav
from cuas.schemas import SensorKind
from cuas.sim.rng import stream
from cuas.sim.sound_link import OnOpen, SoundLink, engine_probabilities
from cuas.sim.station import Look
from cuas.station.detector import load_trained
from cuas.station.look import CachedDetector, LookStream
from cuas.station.recorder import Recorder
from cuas.station.sound import SoundModel, load_sound_model

# No fixed-wing drone is in the footage, so an attack drone has no clips and no real look.
CAMERA_LABELS: Mapping[TargetType, str] = {
    "quadcopter": "drone",
    "friendly_drone": "drone",
    "bird": "bird",
}
BINS_NEAREST_FIRST = ("close", "medium", "distant")
HELD_OUT = "test"
# A zoom camera is a magnified RGB camera: RGB model, RGB clips.
LOOKS_LIKE: Mapping[SensorKind, SensorKind] = {"zoom": "rgb"}


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
        sound: SoundLink | None = None,
        on_open: OnOpen | None = None,
    ) -> None:
        self._sound = sound
        self._on_open = on_open
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
        tick = round(t / self._tick_s)
        if sensor == "acoustic":
            if self._sound is None:
                return None
            return self._sound.hear(
                (station_id, sensor, target_id), target_type, range_m, tick
            )
        label = CAMERA_LABELS.get(target_type)
        model = self._models.get(LOOKS_LIKE.get(sensor, sensor))
        if label is None or model is None:
            return None
        key = (station_id, sensor, target_id)
        wanted = distance_bin(range_m, self._settings.range_bins_m[label])
        state = self._streams.get(key)
        if state is None or state.distance_bin != wanted:
            state = self._open(key, sensor, label, wanted, model, tick)
            self._streams[key] = state
        if tick >= state.next_tick:
            self._advance(state, model, tick)
        return state.result

    def hear_engine(
        self,
        picket_id: str,
        target_id: str,
        target_type: TargetType,
        range_m: float,
        t: float,
    ) -> dict[str, float] | None:
        """Engine type from the real classifier, or ``None`` if nothing stands in for it."""
        if self._sound is None:
            return None
        tick = round(t / self._tick_s)
        look = self._sound.hear((picket_id, target_id), target_type, range_m, tick)
        return None if look is None else engine_probabilities(look.class_probs)

    def _open(
        self,
        key: tuple[str, str, str],
        sensor: SensorKind,
        label: str,
        wanted: str,
        model: LookModel,
        tick: int,
    ) -> _Stream:
        clips = self._candidates(LOOKS_LIKE.get(sensor, sensor), label, wanted)
        if sensor in LOOKS_LIKE:
            # Not a clip any wide camera shows this target with, where another exists.
            wide = {
                state.clip.id
                for (_, other, target_id), state in self._streams.items()
                if target_id == key[2] and other not in LOOKS_LIKE
            }
            clips = [clip for clip in clips if clip.id not in wide] or clips
        rng = stream(self._seed, "clip", *key, wanted)
        clip = clips[int(rng.integers(len(clips)))]
        if clip.id not in self._frames:
            self._frames[clip.id] = self._load_frames(clip)
        if self._on_open:
            self._on_open(key[0], clip)
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


LOOK_SENSORS: tuple[SensorKind, ...] = ("rgb", "thermal")
SOUND_WEIGHTS = "sound.pt"


@dataclass(frozen=True)
class LoadedModels:
    """Models loaded once, for every recorded-media run of a dashboard server to share. The
    detector memo is keyed by clip and frame, so sharing it changes no run's output."""

    looks: Mapping[SensorKind, LookModel]
    sound: SoundModel | None


def look_weights(models_dir: Path, sensor: SensorKind) -> Path:
    return models_dir / f"look_{sensor}.pt"


def load_look_model(
    models_dir: Path, settings: DetectorSettings, sensor: SensorKind
) -> LookModel | None:
    """One camera's trained model, or ``None`` if it has none."""
    weights = look_weights(models_dir, sensor)
    if not weights.exists():
        return None
    record = json.loads(
        (models_dir / f"look_{sensor}.json").read_text(encoding="utf-8")
    )
    detector = load_trained(settings, weights)
    return LookModel(
        CachedDetector(detector.detect), settings.classes, record["high_score"]
    )


def load_look_models(
    models_dir: Path, settings: DetectorSettings
) -> dict[SensorKind, LookModel]:
    """Each camera's trained model. A camera with no trained model has no real look."""
    models = {s: load_look_model(models_dir, settings, s) for s in LOOK_SENSORS}
    return {sensor: model for sensor, model in models.items() if model is not None}


def load_sound(models_dir: Path, ai: StationAiSettings) -> SoundModel | None:
    weights = models_dir / SOUND_WEIGHTS
    return load_sound_model(ai.sound, weights) if weights.exists() else None


def warm_up(models: LoadedModels, ai: StationAiSettings) -> None:
    """One inference per model on blank input, so a run's first look is not the slow one."""
    size = ai.detector.input_size
    for look in models.looks.values():
        look.detector.warm_up(np.zeros((size, size, 3), dtype=np.uint8))
    if models.sound is not None:
        models.sound.classify(np.zeros(ai.sound.window_samples))


def clip_frames(
    data_dir: Path, period_s: float
) -> Callable[[ClipEntry], list[np.ndarray]]:
    """Reads a clip at the look rate, so every frame kept gets used."""

    def load(clip: ClipEntry) -> list[np.ndarray]:
        path = data_dir / clip.path
        return decode_every(path, round(period_s * frame_rate(path)))

    return load


def build_sound_link(
    clips: Sequence[ClipEntry],
    data_dir: Path,
    models_dir: Path,
    ai: StationAiSettings,
    look_every_ticks: int,
    wind_mps: float,
    seed: int,
    on_open: OnOpen,
    model: SoundModel | None = None,
) -> SoundLink | None:
    """``model``: one already loaded; otherwise ``sound.pt`` is loaded here, if it exists."""
    model = model or load_sound(models_dir, ai)
    if model is None:
        return None
    settings = ai.sound

    def load_audio(clip: ClipEntry) -> np.ndarray:
        return read_wav(data_dir / clip.path, settings.sample_rate)

    return SoundLink(
        clips,
        load_audio,
        model.classify,
        settings,
        look_every_ticks,
        wind_mps,
        seed,
        on_open,
    )


def recording_saver(run_dir: Path, data_dir: Path) -> OnOpen:
    """Keeps each recording a station or picket uses, once, under an opaque name."""
    recorder = Recorder(run_dir)
    saved: set[tuple[str, str]] = set()

    def save(owner: str, clip: ClipEntry) -> None:
        if (owner, clip.id) not in saved:
            saved.add((owner, clip.id))
            path = data_dir / clip.path
            recorder.save(owner, clip.id, path.suffix, path.read_bytes())

    return save


def build_media_link(
    config_dir: Path,
    data_dir: Path,
    models_dir: Path,
    run_dir: Path,
    ai: StationAiSettings,
    tick_s: float,
    wind_mps: float,
    seed: int,
    loaded: LoadedModels | None = None,
) -> MediaLink:
    """``loaded``: models a dashboard server loaded once at start; otherwise loaded here."""
    models = loaded.looks if loaded else load_look_models(models_dir, ai.detector)
    if not models:
        raise FileNotFoundError(f"no trained models in {models_dir}")
    clips = load_manifest(config_dir).clips
    look_every_ticks = round(ai.look.period_s / tick_s)
    save = recording_saver(run_dir, data_dir)
    sound_model = loaded.sound if loaded else None
    sound = build_sound_link(
        clips,
        data_dir,
        models_dir,
        ai,
        look_every_ticks,
        wind_mps,
        seed,
        save,
        sound_model,
    )
    return MediaLink(
        clips,
        clip_frames(data_dir, ai.look.period_s),
        models,
        ai.look,
        tick_s,
        seed,
        sound,
        save,
    )
