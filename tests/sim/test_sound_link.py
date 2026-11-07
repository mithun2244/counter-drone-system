import numpy as np
import pytest

from cuas.config import SiteConfig
from cuas.media_manifest import ClipEntry
from cuas.sim.sound_link import SoundLink, engine_probabilities

TONE_CLIP = "1111111111111111"
ENGINE_CLIP = "2222222222222222"
NOISE_CLIP = "3333333333333333"
LOOK_EVERY_TICKS = 3


def entry(clip_id: str, label: str, split: str = "test") -> ClipEntry:
    return ClipEntry(
        id=clip_id,
        path=f"svanstrom/Data/Audio/{label.upper()}_001.wav",
        sha256=clip_id * 4,
        modality="audio",
        label=label,
        split=split,
        group="g",
    )


def clips() -> list[ClipEntry]:
    return [
        entry(TONE_CLIP, "electric_drone"),
        entry(ENGINE_CLIP, "engine"),
        entry(NOISE_CLIP, "background"),
    ]


def load_audio(clip: ClipEntry) -> np.ndarray:
    rng = np.random.default_rng(int(clip.id[0], 16))
    return rng.normal(0.0, 0.2, 16000)


def link(
    site: SiteConfig,
    classify=lambda window: {"electric_drone": 0.1, "engine": 0.2, "background": 0.7},
    entries: list[ClipEntry] | None = None,
    wind: float = 0.0,
    seed: int = 1,
) -> SoundLink:
    return SoundLink(
        clips() if entries is None else entries,
        load_audio,
        classify,
        site.station_ai.sound,
        LOOK_EVERY_TICKS,
        wind,
        seed,
    )


KEY = ("st1", "acoustic", "t1")


def test_class_probs_come_from_the_classifier_not_the_label(site: SiteConfig) -> None:
    look = link(site).hear(KEY, "quadcopter", 100.0, 0)
    assert look.class_probs == {"electric_drone": 0.1, "engine": 0.2, "background": 0.7}


def test_the_recording_follows_the_true_type(site: SiteConfig) -> None:
    media = link(site)
    assert media.hear(KEY, "quadcopter", 100.0, 0).snapshot_ref.startswith(TONE_CLIP)
    other = ("st1", "acoustic", "t2")
    assert media.hear(other, "attack_drone", 100.0, 0).snapshot_ref.startswith(
        ENGINE_CLIP
    )


def test_a_bird_has_nothing_to_hear(site: SiteConfig) -> None:
    assert link(site).hear(KEY, "bird", 100.0, 0) is None


def test_only_held_out_recordings_are_used(site: SiteConfig) -> None:
    entries = [
        entry("aaaa", "electric_drone", split="train"),
        entry("bbbb", "electric_drone", split="test"),
        entry("cccc", "background", split="test"),
    ]
    look = link(site, entries=entries).hear(KEY, "quadcopter", 100.0, 0)
    assert look.snapshot_ref.startswith("bbbb")


def test_held_out_noise_only(site: SiteConfig) -> None:
    entries = [
        entry("bbbb", "electric_drone"),
        entry("cccc", "background", split="train"),
    ]
    assert link(site, entries=entries).hear(KEY, "quadcopter", 100.0, 0) is None


def test_no_engine_recordings_means_no_look_for_an_attack_drone(
    site: SiteConfig,
) -> None:
    entries = [entry(TONE_CLIP, "electric_drone"), entry(NOISE_CLIP, "background")]
    assert link(site, entries=entries).hear(KEY, "attack_drone", 100.0, 0) is None


def test_the_reference_is_opaque(site: SiteConfig) -> None:
    reference = link(site).hear(KEY, "quadcopter", 100.0, 0).snapshot_ref
    for word in ("DRONE", "drone", "svanstrom", ".wav"):
        assert word not in reference


def noise_share(site: SiteConfig, range_m: float, wind: float) -> float:
    """How far the classifier's input drifts from the clean recording."""
    heard: list[np.ndarray] = []

    def classify(window: np.ndarray) -> dict[str, float]:
        heard.append(window)
        return {"background": 1.0}

    link(site, classify, wind=wind).hear(KEY, "quadcopter", range_m, 0)
    audio = load_audio(entry(TONE_CLIP, "electric_drone"))
    size = site.station_ai.sound.window_samples
    return float(np.mean((heard[0] - audio[:size]) ** 2)) if audio.size >= size else 0.0


def test_a_farther_source_gets_more_noise(site: SiteConfig) -> None:
    assert noise_share(site, 2000.0, 0.0) > noise_share(site, 50.0, 0.0)


def test_wind_adds_noise(site: SiteConfig) -> None:
    assert noise_share(site, 100.0, 12.0) > noise_share(site, 100.0, 0.0)


def test_the_classifier_runs_at_the_look_rate(site: SiteConfig) -> None:
    calls: list[int] = []

    def classify(window: np.ndarray) -> dict[str, float]:
        calls.append(1)
        return {"background": 1.0}

    media = link(site, classify)
    for tick in range(LOOK_EVERY_TICKS * 4):
        media.hear(KEY, "quadcopter", 100.0, tick)
    assert len(calls) == 4


def test_recording_choice_is_fixed_by_the_seed(site: SiteConfig) -> None:
    entries = [entry(f"{i:04d}", "electric_drone") for i in range(8)]
    entries.append(entry(NOISE_CLIP, "background"))

    def references(seed: int) -> list[str]:
        return [
            link(site, entries=entries, seed=seed)
            .hear((f"st{i}", "acoustic", "t1"), "quadcopter", 100.0, 0)
            .snapshot_ref
            for i in range(8)
        ]

    assert references(7) == references(7)
    assert references(7) != references(8)


def test_engine_probabilities_ignore_background_and_sum_to_one() -> None:
    result = engine_probabilities(
        {"electric_drone": 0.1, "engine": 0.3, "background": 0.6}
    )
    assert result == pytest.approx({"electric": 0.25, "piston": 0.75})


def test_engine_probabilities_need_both_engine_classes() -> None:
    assert engine_probabilities({"electric_drone": 0.9, "background": 0.1}) is None


def test_engine_probabilities_need_some_evidence() -> None:
    assert engine_probabilities({"electric_drone": 0.0, "engine": 0.0}) is None


def test_each_recording_and_its_noise_are_reported_once(site: SiteConfig) -> None:
    opened: list[tuple[str, str]] = []
    media = SoundLink(
        clips(),
        load_audio,
        lambda window: {"background": 1.0},
        site.station_ai.sound,
        LOOK_EVERY_TICKS,
        0.0,
        1,
        lambda owner, clip: opened.append((owner, clip.id)),
    )
    for tick in range(10):
        media.hear(KEY, "quadcopter", 100.0, tick)
    assert opened == [("st1", TONE_CLIP), ("st1", NOISE_CLIP)]
