"""The hybrid link, with a fake model so no data or weights are needed.

The fake deliberately gets things wrong: if ``class_probs`` followed the label rather than the
model, these tests would notice.
"""

import json
import re
from pathlib import Path

import numpy as np
import pytest
import torch

from cuas.config import SiteConfig
from cuas.media_manifest import ClipEntry
from cuas.schemas import BearingDetection, PicketAlert
from cuas.sim.media import (
    LookModel,
    MediaLink,
    distance_bin,
    load_look_models,
    recording_saver,
)
from cuas.sim.sound_link import SoundLink
from cuas.sim.station import Look
from cuas.station.detector import Box, build_model
from cuas.station.look import CachedDetector
from cuas.station.recorder import verify_recordings

CLASSES = ("drone", "bird", "airplane", "helicopter")
HIGH = 0.5
TICK = 0.2
OPAQUE = "0123456789abcdef"
FRAMES = 6


def entry(
    clip_id: str,
    modality: str = "rgb",
    label: str = "drone",
    split: str = "test",
    distance: str = "distant",
) -> ClipEntry:
    return ClipEntry(
        id=clip_id,
        path=f"svanstrom/Data/V_{label.upper()}_001.mp4",
        sha256=clip_id * 4,
        modality=modality,
        label=label,
        split=split,
        group="g",
        distance_bin=distance,
    )


def frames_for(clip: ClipEntry) -> list[np.ndarray]:
    return [np.zeros((16, 32, 3), dtype=np.uint8) for _ in range(FRAMES)]


def model_saying(class_name: str, score: float = 0.9) -> LookModel:
    """A model that always reports one class, whatever it is shown."""

    def detect(frame: np.ndarray) -> list[Box]:
        return [Box(10, 4, 14, 8, score, class_name)]

    return LookModel(CachedDetector(detect), CLASSES, HIGH)


def link(
    site: SiteConfig, clips: list[ClipEntry], model: LookModel, seed: int = 1
) -> MediaLink:
    return MediaLink(
        clips, frames_for, {"rgb": model}, site.station_ai.look, TICK, seed
    )


def looks(
    media: MediaLink, target_type: str = "quadcopter", range_m: float = 300.0
) -> list:
    return [
        media.look("st1", "rgb", "t1", target_type, range_m, i * TICK)
        for i in range(60)
    ]


@pytest.mark.parametrize(
    ("range_m", "expected"),
    [
        (5.0, "close"),
        (19.9, "close"),
        (20.0, "medium"),
        (59.9, "medium"),
        (60.0, "distant"),
    ],
)
def test_distance_bins_follow_the_dataset(range_m: float, expected: str) -> None:
    assert distance_bin(range_m, (20.0, 60.0)) == expected


def test_class_probs_come_from_the_model_not_the_label(site: SiteConfig) -> None:
    """A drone clip, but the model says bird: the output must say bird."""
    media = link(site, [entry(OPAQUE)], model_saying("bird"))
    final = looks(media)[-1]
    assert final.class_probs["bird"] == pytest.approx(0.9)
    assert final.class_probs["drone"] == 0.0


def test_every_class_is_reported_and_unconfirmed_looks_are_zero(
    site: SiteConfig,
) -> None:
    media = link(site, [entry(OPAQUE)], model_saying("drone"))
    first = looks(media)[0]
    assert set(first.class_probs) == set(CLASSES)
    assert set(first.class_probs.values()) == {0.0}


def test_snapshot_ref_is_opaque(site: SiteConfig) -> None:
    media = link(site, [entry(OPAQUE)], model_saying("drone"))
    for look in looks(media):
        clip_id, frame = look.snapshot_ref.split(":")
        assert clip_id == OPAQUE
        assert frame.isdigit()
        for word in ("DRONE", "drone", "svanstrom", ".mp4"):
            assert word not in look.snapshot_ref


def test_only_held_out_clips_are_ever_used(site: SiteConfig) -> None:
    clips = [
        entry("aaaa", split="train"),
        entry("bbbb", split="val"),
        entry("cccc", split="test"),
    ]
    media = link(site, clips, model_saying("drone"))
    assert {look.snapshot_ref.split(":")[0] for look in looks(media)} == {"cccc"}


def test_no_held_out_clips_is_an_error_not_a_silent_fallback(site: SiteConfig) -> None:
    media = link(site, [entry("aaaa", split="train")], model_saying("drone"))
    with pytest.raises(ValueError, match="no held-out"):
        looks(media)


def test_clips_are_matched_to_the_simulated_range(site: SiteConfig) -> None:
    clips = [entry("near", distance="close"), entry("far", distance="distant")]
    media = link(site, clips, model_saying("drone"))
    assert looks(media, range_m=5.0)[0].snapshot_ref.startswith("near")
    media = link(site, clips, model_saying("drone"))
    assert looks(media, range_m=500.0)[0].snapshot_ref.startswith("far")


def test_the_nearest_bin_stands_in_when_one_is_empty(site: SiteConfig) -> None:
    media = link(site, [entry("mid", distance="medium")], model_saying("drone"))
    assert looks(media, range_m=500.0)[0].snapshot_ref.startswith("mid")


def test_a_bird_target_pulls_a_bird_clip(site: SiteConfig) -> None:
    clips = [entry("dddd"), entry("bbbb", label="bird")]
    media = link(site, clips, model_saying("drone"))
    assert looks(media, "bird")[0].snapshot_ref.startswith("bbbb")


def test_an_attack_drone_has_no_clip_so_no_real_look(site: SiteConfig) -> None:
    media = link(site, [entry(OPAQUE)], model_saying("drone"))
    assert looks(media, "attack_drone") == [None] * 60


def test_a_sensor_without_a_model_has_no_look(site: SiteConfig) -> None:
    media = link(site, [entry(OPAQUE)], model_saying("drone"))
    assert media.look("st1", "acoustic", "t1", "quadcopter", 100.0, 0.0) is None


def test_the_model_runs_at_the_look_rate_and_results_repeat_between(
    site: SiteConfig,
) -> None:
    calls: list[str] = []

    class Counting(CachedDetector):
        def boxes(self, frame_key: str, frame: np.ndarray) -> list[Box]:
            calls.append(frame_key)
            return []

    model = LookModel(Counting(lambda f: []), CLASSES, HIGH)
    media = link(site, [entry(OPAQUE)], model)
    looks(media)  # 12 simulated seconds at 5 ticks per second
    assert len(calls) == 12 / site.station_ai.look.period_s


def test_a_look_period_that_is_not_whole_ticks_is_refused(site: SiteConfig) -> None:
    settings = site.station_ai.look.model_copy(update={"period_s": 0.5})
    with pytest.raises(ValueError, match="whole number"):
        MediaLink([], frames_for, {}, settings, TICK, 1)


def test_each_stream_is_independent(site: SiteConfig) -> None:
    clips = [entry(f"{i:04d}") for i in range(8)]
    media = link(site, clips, model_saying("drone"))
    chosen = {
        media.look(f"st{i}", "rgb", "t1", "quadcopter", 300.0, 0.0).snapshot_ref
        for i in range(8)
    }
    assert len(chosen) > 1


def test_clip_choice_is_fixed_by_the_seed(site: SiteConfig) -> None:
    clips = [entry(f"{i:04d}") for i in range(8)]
    refs = [link(site, clips, model_saying("drone"), seed=7) for _ in range(2)]
    first, second = [[look.snapshot_ref for look in looks(m)] for m in refs]
    assert first == second
    other = [
        look.snapshot_ref
        for look in looks(link(site, clips, model_saying("drone"), seed=8))
    ]
    assert first != other


def fake_media(site: SiteConfig) -> MediaLink:
    clips = [
        entry("aaaa"),
        entry("bbbb", label="bird"),
        entry("cccc", distance="medium"),
    ]
    return link(site, clips, model_saying("drone"), seed=3)


def strip_model_output(bearing: BearingDetection) -> str:
    return bearing.model_copy(
        update={"class_probs": {}, "snapshot_ref": None}
    ).model_dump_json()


async def test_media_leaves_the_simulated_geometry_untouched(record, site) -> None:
    plain, _ = await record("s2", seed=7)
    linked, _ = await record("s2", seed=7, media=fake_media(site))
    assert len(plain) == len(linked)
    for a, b in zip(plain, linked, strict=True):
        if isinstance(a, BearingDetection):
            assert strip_model_output(a) == strip_model_output(b)
        else:
            assert a == b


async def test_cameras_carry_model_output_and_no_truth(record, site) -> None:
    messages, truth = await record("s3", seed=7, media=fake_media(site))
    bearings = [m for m in messages if isinstance(m, BearingDetection)]
    cameras = [b for b in bearings if b.sensor == "rgb"]
    assert cameras
    assert all(b.class_probs and b.snapshot_ref for b in cameras)
    words = {s.target_id for s in truth.states}
    words |= {"quadcopter", "friendly_drone", "attack_drone", "svanstrom", ".mp4"}
    for message in messages:
        text = message.model_dump_json()
        assert not [word for word in words if word in text]


async def test_a_run_with_media_is_repeatable(record, site) -> None:
    first, _ = await record("s2", seed=7, media=fake_media(site))
    second, _ = await record("s2", seed=7, media=fake_media(site))
    assert [m.model_dump_json() for m in first] == [m.model_dump_json() for m in second]


async def test_attack_drones_keep_empty_camera_output(record, site) -> None:
    messages, _ = await record("s1", seed=7, media=fake_media(site))
    bearings = [m for m in messages if isinstance(m, BearingDetection)]
    assert bearings
    assert all(b.class_probs == {} and b.snapshot_ref is None for b in bearings)


class FakeSound:
    """Stands in for the sound link, to check the routing."""

    def __init__(self) -> None:
        self.keys: list[tuple[str, ...]] = []

    def hear(self, key, target_type, range_m, tick):
        self.keys.append(key)
        return Look({"electric_drone": 0.2, "engine": 0.6, "background": 0.2}, "abcd:0")


def media_with_sound(site: SiteConfig) -> MediaLink:
    return MediaLink(
        [entry(OPAQUE)],
        frames_for,
        {"rgb": model_saying("drone")},
        site.station_ai.look,
        TICK,
        1,
        FakeSound(),
    )


def test_acoustic_sensors_go_to_the_sound_link(site: SiteConfig) -> None:
    look = media_with_sound(site).look(
        "st1", "acoustic", "t1", "quadcopter", 100.0, 0.0
    )
    assert look.class_probs["engine"] == 0.6


def test_pickets_get_engine_type_from_the_classifier(site: SiteConfig) -> None:
    result = media_with_sound(site).hear_engine("pk1", "t1", "attack_drone", 500.0, 0.0)
    assert result == pytest.approx({"electric": 0.25, "piston": 0.75})


def test_without_a_sound_model_pickets_keep_their_mock(site: SiteConfig) -> None:
    media = link(site, [entry(OPAQUE)], model_saying("drone"))
    assert media.hear_engine("pk1", "t1", "attack_drone", 500.0, 0.0) is None


async def test_pickets_report_the_classifier_and_their_geometry_is_unchanged(
    record, site
) -> None:
    plain, _ = await record("s1", seed=7)
    linked, truth = await record("s1", seed=7, media=media_with_sound(site))
    alerts = [m for m in linked if isinstance(m, PicketAlert)]
    assert alerts
    assert all(
        a.engine_type_probs == pytest.approx({"electric": 0.25, "piston": 0.75})
        for a in alerts
    )
    assert all(t.guessed_engine_type == "piston" for t in truth.picket_alerts)
    plain_alerts = [m for m in plain if isinstance(m, PicketAlert)]
    assert [(a.t, a.picket_id, a.bearing_deg) for a in alerts] == [
        (a.t, a.picket_id, a.bearing_deg) for a in plain_alerts
    ]


def test_each_clip_used_is_reported_once_per_stream(site: SiteConfig) -> None:
    opened: list[tuple[str, str]] = []
    media = MediaLink(
        [entry(OPAQUE)],
        frames_for,
        {"rgb": model_saying("drone")},
        site.station_ai.look,
        TICK,
        1,
        None,
        lambda owner, clip: opened.append((owner, clip.id)),
    )
    looks(media)
    assert opened == [("st1", OPAQUE)]


def test_recording_saver_keeps_each_clip_once_per_owner_with_an_opaque_name(
    tmp_path,
) -> None:
    data = tmp_path / "data"
    source = data / "svanstrom" / "V_DRONE_001.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"clip")
    save = recording_saver(tmp_path / "run", data)
    clip = entry(OPAQUE).model_copy(update={"path": "svanstrom/V_DRONE_001.mp4"})
    save("st1", clip)
    save("st1", clip)
    save("st2", clip)
    saved = tmp_path / "run" / "station_st1" / f"{OPAQUE}.mp4"
    assert saved.read_bytes() == b"clip"
    assert (tmp_path / "run" / "station_st2" / f"{OPAQUE}.mp4").exists()
    assert verify_recordings(tmp_path / "run") == []
    assert "DRONE" not in saved.name


# Real SSD weights with their last layers set by hand, so loading, inference, the tracker and M-of-N
# all run as they do in a demo, with a known answer and no download.
LAST_HEAD_LAYER = re.compile(r"head\.\w+_head\.module_list\.\d+\.1\.(weight|bias)")
CERTAIN_LOGIT = 10.0
CONFIDENT = 0.9
RGB_THRESHOLD = 0.15
THERMAL_THRESHOLD = 0.2
RGB_CLIP = "aaaaaaaaaaaaaaaa"
THERMAL_CLIP = "bbbbbbbbbbbbbbbb"
SOUND_CLIP = "cccccccccccccccc"
NOISE_CLIP = "dddddddddddddddd"
HEARD_DRONE = 0.8


def save_model_saying(
    class_name: str, sensor: str, threshold: float, settings, folder: Path
) -> None:
    """A checkpoint that reports one class on every anchor, whatever the pixels show."""
    state = build_model(settings).state_dict()
    columns = len(settings.classes) + 1  # label 0 is background
    target = settings.classes.index(class_name) + 1
    for name, value in state.items():
        if LAST_HEAD_LAYER.fullmatch(name):
            value.zero_()
            if "classification" in name and name.endswith("bias"):
                value[target::columns] = CERTAIN_LOGIT
    torch.save(state, folder / f"look_{sensor}.pt")
    (folder / f"look_{sensor}.json").write_text(
        json.dumps({"high_score": threshold}), encoding="utf-8"
    )


def saved_camera_models(
    site: SiteConfig, folder: Path, rgb: str, thermal: str
) -> dict[str, LookModel]:
    settings = site.station_ai.detector
    save_model_saying(rgb, "rgb", RGB_THRESHOLD, settings, folder)
    save_model_saying(thermal, "thermal", THERMAL_THRESHOLD, settings, folder)
    return load_look_models(folder, settings)


def s2_media(
    site: SiteConfig, models: dict[str, LookModel], sound: SoundLink | None = None
) -> MediaLink:
    clips = [entry(RGB_CLIP, "rgb"), entry(THERMAL_CLIP, "thermal")]
    return MediaLink(clips, frames_for, models, site.station_ai.look, TICK, 7, sound)


def sound_that_hears_a_drone(site: SiteConfig) -> SoundLink:
    settings = site.station_ai.sound
    clips = [
        entry(SOUND_CLIP, "audio", "electric_drone"),
        entry(NOISE_CLIP, "audio", "background"),
    ]
    return SoundLink(
        clips,
        lambda clip: np.random.default_rng(1).normal(0.0, 0.2, settings.window_samples),
        lambda window: {
            "electric_drone": HEARD_DRONE,
            "engine": 0.1,
            "background": 0.1,
        },
        settings,
        round(site.station_ai.look.period_s / TICK),
        0.0,
        1,
    )


async def test_s2_carries_a_controlled_positive_from_every_sensor(
    record, site, tmp_path: Path
) -> None:
    """Models built to say drone must reach the bus as non-zero, so all-zero output fails."""
    models = saved_camera_models(site, tmp_path, rgb="drone", thermal="drone")
    media = s2_media(site, models, sound_that_hears_a_drone(site))
    messages, _ = await record("s2", seed=7, media=media)
    bearings = [m for m in messages if isinstance(m, BearingDetection)]
    expected = {
        "rgb": ("drone", CONFIDENT),
        "thermal": ("drone", CONFIDENT),
        "acoustic": ("electric_drone", HEARD_DRONE),
    }
    for sensor, (class_name, least) in expected.items():
        scores = [b.class_probs[class_name] for b in bearings if b.sensor == sensor]
        assert scores, sensor
        assert max(scores) >= least, sensor


async def test_s2_thermal_bearings_come_from_the_thermal_model(
    record, site, tmp_path: Path
) -> None:
    """Each camera's weights say a different class, so a swapped model shows in the output."""
    models = saved_camera_models(site, tmp_path, rgb="bird", thermal="drone")
    assert models["thermal"].high_score == THERMAL_THRESHOLD
    assert models["rgb"].high_score == RGB_THRESHOLD
    messages, _ = await record("s2", seed=7, media=s2_media(site, models))
    bearings = [m for m in messages if isinstance(m, BearingDetection)]
    expected = {
        "thermal": ("drone", "bird", THERMAL_CLIP),
        "rgb": ("bird", "drone", RGB_CLIP),
    }
    for sensor, (own, other, clip_id) in expected.items():
        chosen = [b for b in bearings if b.sensor == sensor]
        assert chosen, sensor
        assert max(b.class_probs[own] for b in chosen) >= CONFIDENT, sensor
        assert max(b.class_probs[other] for b in chosen) == 0.0, sensor
        assert {b.snapshot_ref.split(":")[0] for b in chosen} == {clip_id}
