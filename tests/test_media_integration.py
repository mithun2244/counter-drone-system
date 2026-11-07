"""Checks on the real recordings and models. Skipped when they have not been downloaded."""

import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from cuas.config import load_site
from cuas.media_manifest import MANIFEST_NAME, MediaManifest, load_manifest
from cuas.metrics.mat_labels import read_label_file
from cuas.recordings import frame_count
from cuas.schemas import BearingDetection, PicketAlert
from cuas.sim.media import MediaLink, build_media_link
from cuas.sim.scenario import load_scenario
from cuas.station.detector import build_model, load_starting_weights
from cuas.station.recorder import verify_recordings

pytestmark = pytest.mark.media

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
SEED = 7
COCO_WEIGHTS = (
    ROOT / "models" / "pretrained" / "ssdlite320_mobilenet_v3_large_coco-a79551df.pth"
)


@pytest.fixture(scope="module")
def manifest() -> MediaManifest:
    if (
        not (CONFIG_DIR / MANIFEST_NAME).exists()
        or not (DATA_DIR / "svanstrom").exists()
    ):
        pytest.skip("recordings not downloaded")
    return load_manifest(CONFIG_DIR)


def test_no_clip_is_listed_twice(manifest: MediaManifest) -> None:
    ids = [clip.id for clip in manifest.clips]
    paths = [clip.path for clip in manifest.clips]
    assert len(ids) == len(set(ids))
    assert len(paths) == len(set(paths))


def test_no_group_spans_two_splits(manifest: MediaManifest) -> None:
    splits: defaultdict[str, set[str]] = defaultdict(set)
    for clip in manifest.clips:
        splits[clip.group].add(clip.split)
    assert not {group: found for group, found in splits.items() if len(found) > 1}


def test_all_third_party_clips_are_excluded(manifest: MediaManifest) -> None:
    excluded = {entry.path for entry in manifest.excluded}
    assert not excluded & {clip.path for clip in manifest.clips}
    video = [
        e.path
        for e in manifest.excluded
        if "third-party" in e.reason and e.path.endswith(".mp4")
    ]
    assert len(video) == 49
    assert Counter("HELICOPTER" in p for p in video) == {True: 38, False: 11}


def test_all_helicopter_audio_is_excluded(manifest: MediaManifest) -> None:
    excluded = [
        e.path
        for e in manifest.excluded
        if "HELICOPTER" in e.path and e.path.endswith(".wav")
    ]
    assert len(excluded) == 30
    assert not [
        c for c in manifest.clips if c.modality == "audio" and "HELICOPTER" in c.path
    ]


def test_every_modality_and_label_has_enough_held_out_clips(
    manifest: MediaManifest,
) -> None:
    minimum = load_site(CONFIG_DIR).station_ai.split.min_test_clips
    counts = Counter(
        (clip.modality, clip.label) for clip in manifest.clips if clip.split == "test"
    )
    every = {(clip.modality, clip.label) for clip in manifest.clips}
    assert {key: counts[key] for key in every if counts[key] < minimum} == {}


def test_held_out_noise_is_never_used_in_training(manifest: MediaManifest) -> None:
    noise = [c for c in manifest.clips if c.label == "background"]
    assert {c.split for c in noise} == {"train", "val", "test"}
    train = {c.id for c in noise if c.split == "train"}
    test = {c.id for c in noise if c.split == "test"}
    assert not train & test


def test_no_scene_crosses_train_and_test(manifest: MediaManifest) -> None:
    assert manifest.same_label_scene_pairs == 0


def test_exact_copies_are_excluded(manifest: MediaManifest) -> None:
    assert len({clip.sha256 for clip in manifest.clips}) == len(manifest.clips)
    reasons = {entry.path: entry.reason for entry in manifest.excluded}
    assert "exact copy" in reasons["svanstrom/Data/Audio/BACKGROUND_019.wav"]


def test_opaque_ids_reveal_no_label(manifest: MediaManifest) -> None:
    for clip in manifest.clips:
        assert len(clip.id) == 16
        assert clip.sha256.startswith(clip.id)
        assert clip.label.lower() not in clip.id


def test_real_starting_weights_load_with_only_the_class_head_skipped() -> None:
    if not COCO_WEIGHTS.exists():
        pytest.skip("starting weights not downloaded")
    model = build_model(load_site(CONFIG_DIR).station_ai.detector)
    skipped = load_starting_weights(model, COCO_WEIGHTS)
    assert skipped
    assert all(name.startswith("head.classification_head") for name in skipped)


def clip_named(manifest: MediaManifest, name: str):
    return next(c for c in manifest.clips if c.path.endswith(name))


def test_labels_line_up_with_frames_and_the_clip_label(manifest: MediaManifest) -> None:
    for name in ("IR_DRONE_001.mp4", "V_BIRD_001.mp4", "V_HELICOPTER_001.mp4"):
        clip = clip_named(manifest, name)
        count = frame_count(DATA_DIR / clip.path)
        frames = read_label_file(DATA_DIR / clip.labels_path, count)
        assert len(frames) == count
        assert any(box.class_name == clip.label for frame in frames for box in frame)


def test_two_drone_frames_keep_both_boxes(manifest: MediaManifest) -> None:
    clip = clip_named(manifest, "IR_DRONE_143.mp4")
    count = frame_count(DATA_DIR / clip.path)
    frames = read_label_file(DATA_DIR / clip.labels_path, count)
    assert max(len(frame) for frame in frames) >= 2


def test_every_kept_label_file_is_readable(manifest: MediaManifest) -> None:
    videos = [c for c in manifest.clips if c.labels_path]
    assert len(videos) == 600
    excluded = {e.path: e.reason for e in manifest.excluded}
    assert "label" in excluded["svanstrom/Data/Video_V/V_AIRPLANE_002.mp4"]


def test_engine_clips_are_cc0_with_no_uploader_in_two_splits(
    manifest: MediaManifest,
) -> None:
    selection_path = DATA_DIR / "fsd50k" / "selected.json"
    if not selection_path.exists():
        pytest.skip("engine clips not downloaded")
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    assert all("publicdomain/zero" in clip["license"] for clip in selection)
    uploader_of = {clip["fname"]: clip["uploader"] for clip in selection}
    engines = [c for c in manifest.clips if c.label == "engine"]
    assert engines
    splits: defaultdict[str, set[str]] = defaultdict(set)
    for clip in engines:
        fname = Path(clip.path).stem
        splits[uploader_of[fname]].add(clip.split)
    assert all(len(found) == 1 for found in splits.values())
    assert {clip.split for clip in engines} == {"train", "val", "test"}


def test_no_uploader_name_is_stored_in_the_manifest(manifest: MediaManifest) -> None:
    selection_path = DATA_DIR / "fsd50k" / "selected.json"
    if not selection_path.exists():
        pytest.skip("engine clips not downloaded")
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    text = (CONFIG_DIR / MANIFEST_NAME).read_text(encoding="utf-8")
    assert not [c["uploader"] for c in selection if f"_{c['uploader']}" in text]


MODELS_DIR = ROOT / "models"
TRUTH_WORDS = ("quadcopter", "attack_drone", "svanstrom", "fsd50k", ".mp4", ".wav")


@pytest.fixture
def real_media(manifest: MediaManifest, tmp_path: Path):
    """Factory for a real media link. Skipped until the RGB and sound models exist."""
    needed = [MODELS_DIR / f"{name}.pt" for name in ("look_rgb", "sound")]
    if not all(path.exists() for path in needed):
        pytest.skip("models not trained")
    site = load_site(CONFIG_DIR)

    def build(wind_mps: float, seed: int, run_dir: Path | None = None) -> MediaLink:
        return build_media_link(
            CONFIG_DIR,
            DATA_DIR,
            MODELS_DIR,
            run_dir or tmp_path,
            site.station_ai,
            site.simulation.tick_s,
            wind_mps,
            seed,
        )

    return build


def s2_wind() -> float:
    return load_scenario(CONFIG_DIR, "s2").environment.wind_mps


def strip_look(bearing: BearingDetection) -> str:
    return bearing.model_copy(
        update={"class_probs": {}, "snapshot_ref": None}
    ).model_dump_json()


async def test_s2_bearings_carry_real_output_and_the_same_geometry(
    record, real_media, manifest: MediaManifest
) -> None:
    if not (MODELS_DIR / "look_thermal.pt").exists():
        pytest.skip("thermal model not trained")
    plain, _ = await record("s2", seed=SEED)
    linked, _ = await record("s2", seed=SEED, media=real_media(s2_wind(), SEED))
    assert len(plain) == len(linked)
    bearings = [m for m in linked if isinstance(m, BearingDetection)]
    assert {b.sensor for b in bearings} == {"rgb", "thermal", "acoustic"}
    held_out = {c.id for c in manifest.clips if c.split == "test"}
    for bearing in bearings:
        assert bearing.class_probs
        assert bearing.snapshot_ref is not None
        assert bearing.snapshot_ref.split(":")[0] in held_out
    for a, b in zip(plain, linked, strict=True):
        if isinstance(a, BearingDetection):
            assert strip_look(a) == strip_look(b)


async def test_tracks_use_geometry_only_so_real_models_change_nothing(
    record_pipeline, real_media
) -> None:
    _, _, plain, _ = await record_pipeline("s2", seed=SEED)
    _, _, linked, _ = await record_pipeline(
        "s2", seed=SEED, media=real_media(s2_wind(), SEED)
    )
    assert plain
    assert [m.model_dump_json() for m in plain] == [m.model_dump_json() for m in linked]


async def test_s2_with_real_models_is_repeatable(record, real_media) -> None:
    first, _ = await record("s2", seed=SEED, media=real_media(s2_wind(), SEED))
    second, _ = await record("s2", seed=SEED, media=real_media(s2_wind(), SEED))
    assert [m.model_dump_json() for m in first] == [m.model_dump_json() for m in second]


async def test_a_real_media_run_leaks_no_truth(record, real_media) -> None:
    messages, truth = await record("s2", seed=SEED, media=real_media(s2_wind(), SEED))
    words = {*TRUTH_WORDS, *(state.target_id for state in truth.states)}
    for message in messages:
        text = message.model_dump_json()
        assert not [word for word in words if word in text]


async def test_the_recorder_keeps_verifiable_copies(
    record, real_media, tmp_path: Path
) -> None:
    run_dir = tmp_path / "run"
    await record("s2", seed=SEED, media=real_media(s2_wind(), SEED, run_dir))
    stations = sorted(path.name for path in run_dir.iterdir())
    assert stations == ["station_st1", "station_st2", "station_st3"]
    assert verify_recordings(run_dir) == []
    saved = next(run_dir.glob("station_st1/*.mp4"))
    assert not [word for word in ("DRONE", "BIRD", "V_", "IR_") if word in saved.name]
    saved.write_bytes(saved.read_bytes() + b"x")
    assert "hash mismatch" in verify_recordings(run_dir)[0]


async def test_s1_pickets_use_the_real_classifier(record, real_media) -> None:
    wind = load_scenario(CONFIG_DIR, "s1").environment.wind_mps
    messages, _ = await record("s1", seed=SEED, media=real_media(wind, SEED))
    alerts = [m for m in messages if isinstance(m, PicketAlert)]
    assert alerts
    for alert in alerts:
        assert set(alert.engine_type_probs) == {"electric", "piston"}
        assert sum(alert.engine_type_probs.values()) == pytest.approx(1.0)
    cameras = [
        m
        for m in messages
        if isinstance(m, BearingDetection) and m.sensor != "acoustic"
    ]
    assert all(b.class_probs == {} for b in cameras)  # no fixed-wing footage exists
