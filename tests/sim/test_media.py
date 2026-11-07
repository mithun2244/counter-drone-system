"""The hybrid link, with a fake model so no data or weights are needed.

The fake deliberately gets things wrong: if ``class_probs`` followed the label rather than the
model, these tests would notice.
"""

import numpy as np
import pytest

from cuas.config import SiteConfig
from cuas.media_manifest import ClipEntry
from cuas.schemas import BearingDetection
from cuas.sim.media import LookModel, MediaLink, distance_bin
from cuas.station.detector import Box
from cuas.station.look import CachedDetector

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
