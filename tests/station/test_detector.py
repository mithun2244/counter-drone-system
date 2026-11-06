import inspect
from pathlib import Path

import numpy as np
import pytest
import torch

from cuas.config import DetectorSettings, SiteConfig
from cuas.station.detector import (
    Detector,
    build_model,
    copy_except_class_head,
    frame_to_tensor,
    load_starting_weights,
)

SMALL_SIZE = 128  # keeps these tests quick; the real size comes from site.yaml
COCO_CLASSES = 91  # classes the starting weights were trained on, with background


@pytest.fixture
def settings(site: SiteConfig) -> DetectorSettings:
    return site.station_ai.detector.model_copy(update={"input_size": SMALL_SIZE})


def test_a_frame_becomes_a_scaled_channel_first_tensor() -> None:
    frame = np.zeros((4, 6, 3), dtype=np.uint8)
    frame[0, 0] = (255, 0, 51)
    tensor = frame_to_tensor(frame)
    assert tensor.shape == (3, 4, 6)
    assert tensor[:, 0, 0].tolist() == pytest.approx([1.0, 0.0, 0.2])


def test_model_uses_our_input_size_and_class_count(settings: DetectorSettings) -> None:
    model = build_model(settings)
    assert model.transform.fixed_size == (SMALL_SIZE, SMALL_SIZE)
    assert model.head.classification_head.num_columns == len(settings.classes) + 1


def test_smallest_box_is_much_smaller_than_the_torchvision_default(
    settings: DetectorSettings,
) -> None:
    assert build_model(settings).anchor_generator.scales[0] == settings.anchor_scales[0]
    assert settings.anchor_scales[0] < 0.2


def test_detector_returns_boxes_in_original_frame_coordinates_with_our_classes(
    settings: DetectorSettings,
) -> None:
    torch.manual_seed(0)
    relaxed = settings.model_copy(update={"min_score": 0.0})
    frame = np.random.default_rng(0).integers(0, 255, (64, 96, 3), dtype=np.uint8)
    boxes = Detector(build_model(relaxed), relaxed).detect(frame)
    assert boxes  # an untrained model reports plenty of low-confidence boxes
    for box in boxes:
        assert box.class_name in relaxed.classes
        assert -1.0 <= box.x1 <= box.x2 <= 97.0
        assert -1.0 <= box.y1 <= box.y2 <= 65.0


def test_min_score_filters_boxes(settings: DetectorSettings) -> None:
    torch.manual_seed(0)
    strict = settings.model_copy(update={"min_score": 1.0})
    frame = np.zeros((64, 96, 3), dtype=np.uint8)
    assert Detector(build_model(strict), strict).detect(frame) == []


def test_inference_is_repeatable(settings: DetectorSettings) -> None:
    torch.manual_seed(0)
    relaxed = settings.model_copy(update={"min_score": 0.0})
    detector = Detector(build_model(relaxed), relaxed)
    frame = np.random.default_rng(1).integers(0, 255, (64, 96, 3), dtype=np.uint8)
    assert detector.detect(frame) == detector.detect(frame)


def coco_shaped_state(settings: DetectorSettings) -> dict[str, torch.Tensor]:
    torch.manual_seed(1)
    return build_model(settings, num_classes=COCO_CLASSES).state_dict()


def test_shared_weights_copy_and_the_class_head_is_skipped(
    settings: DetectorSettings,
) -> None:
    torch.manual_seed(2)
    model = build_model(settings)
    state = coco_shaped_state(settings)
    skipped = copy_except_class_head(model, state)
    assert skipped
    assert all(name.startswith("head.classification_head") for name in skipped)
    for name, value in model.state_dict().items():
        if name not in skipped:
            assert torch.equal(value, state[name])


def test_starting_weights_load_from_a_file(
    settings: DetectorSettings, tmp_path: Path
) -> None:
    path = tmp_path / "coco.pth"
    state = coco_shaped_state(settings)
    torch.save(state, path)
    model = build_model(settings)
    assert load_starting_weights(model, path)
    name = next(k for k in state if k.startswith("backbone.") and "weight" in k)
    assert torch.equal(model.state_dict()[name], state[name])


def test_the_detector_cannot_be_given_a_label_path_or_target() -> None:
    assert list(inspect.signature(Detector.detect).parameters) == ["self", "frame"]
