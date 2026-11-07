"""The hybrid link for sound: truth picks a held-out recording, then the true range and wind set
how much noise is mixed in. The classifier hears the mixed samples only.
"""

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from cuas.config import SoundSettings, TargetType
from cuas.media_manifest import ClipEntry
from cuas.sim.mixing import fit_length, mix_at_snr, snr_for
from cuas.sim.rng import stream
from cuas.sim.station import Look

# The engine recordings are a proxy: mostly road vehicles, not one-way attack drones.
SOUND_LABELS: Mapping[TargetType, str] = {
    "quadcopter": "electric_drone",
    "friendly_drone": "electric_drone",
    "attack_drone": "engine",
}
ENGINE_OF_CLASS = {"electric_drone": "electric", "engine": "piston"}
NOISE_LABEL = "background"
HELD_OUT = "test"

Classify = Callable[[np.ndarray], dict[str, float]]
LoadAudio = Callable[[ClipEntry], np.ndarray]
OnOpen = Callable[[str, ClipEntry], None]


@dataclass
class _SoundStream:
    clip: ClipEntry
    audio: np.ndarray
    noise: np.ndarray
    position: int
    noise_position: int
    next_tick: int
    result: Look | None = None


def engine_probabilities(class_probs: Mapping[str, float]) -> dict[str, float] | None:
    """Engine type given that an engine was heard, so these two sum to one."""
    engines = {
        ENGINE_OF_CLASS[name]: score
        for name, score in class_probs.items()
        if name in ENGINE_OF_CLASS
    }
    total = sum(engines.values())
    if len(engines) < len(ENGINE_OF_CLASS) or total <= 0.0:
        return None
    return {name: score / total for name, score in sorted(engines.items())}


class SoundLink:
    """Held-out recordings and held-out noise only."""

    def __init__(
        self,
        clips: Sequence[ClipEntry],
        load_audio: LoadAudio,
        classify: Classify,
        settings: SoundSettings,
        look_every_ticks: int,
        wind_mps: float,
        seed: int,
        on_open: OnOpen | None = None,
    ) -> None:
        self._on_open = on_open
        self._load_audio = load_audio
        self._classify = classify
        self._settings = settings
        self._look_every_ticks = look_every_ticks
        self._wind_mps = wind_mps
        self._seed = seed
        self._clips: defaultdict[str, list[ClipEntry]] = defaultdict(list)
        for clip in sorted(clips, key=lambda c: c.id):
            if clip.modality == "audio" and clip.split == HELD_OUT:
                self._clips[clip.label].append(clip)
        self._audio: dict[str, np.ndarray] = {}
        self._streams: dict[tuple[str, ...], _SoundStream] = {}

    def hear(
        self,
        key: tuple[str, ...],
        target_type: TargetType,
        range_m: float,
        tick: int,
    ) -> Look | None:
        """What the classifier reports for this source, or ``None`` if nothing stands in for it."""
        label = SOUND_LABELS.get(target_type)
        if label is None or not self._clips[label] or not self._clips[NOISE_LABEL]:
            return None
        state = self._streams.get(key)
        if state is None:
            state = self._open(key, label, tick)
            self._streams[key] = state
        if tick >= state.next_tick:
            self._advance(state, range_m, tick)
        return state.result

    def _open(self, key: tuple[str, ...], label: str, tick: int) -> _SoundStream:
        rng = stream(self._seed, "sound", *key)
        clips, noises = self._clips[label], self._clips[NOISE_LABEL]
        clip = clips[int(rng.integers(len(clips)))]
        noise = noises[int(rng.integers(len(noises)))]
        audio, noise_audio = self._load(clip), self._load(noise)
        if self._on_open:
            self._on_open(key[0], clip)
            self._on_open(key[0], noise)
        return _SoundStream(
            clip,
            audio,
            noise_audio,
            int(rng.integers(audio.size)),
            int(rng.integers(noise_audio.size)),
            tick,
        )

    def _load(self, clip: ClipEntry) -> np.ndarray:
        if clip.id not in self._audio:
            self._audio[clip.id] = self._load_audio(clip)
        return self._audio[clip.id]

    def _advance(self, state: _SoundStream, range_m: float, tick: int) -> None:
        size = self._settings.window_samples
        window = fit_length(state.audio, size, state.position)
        noise = fit_length(state.noise, size, state.noise_position)
        snr = snr_for(range_m, self._wind_mps, self._settings.mixing)
        mixed = mix_at_snr(window, noise, snr)
        reference = f"{state.clip.id}:{state.position // size}"
        state.result = Look(self._classify(mixed), reference)
        state.position += size
        state.noise_position += size
        state.next_tick = tick + self._look_every_ticks
