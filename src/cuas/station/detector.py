"""Video detector: frame in, boxes out. It never sees a label, path or target ID."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torchvision.models.detection import ssdlite320_mobilenet_v3_large
from torchvision.models.detection.anchor_utils import DefaultBoxGenerator
from torchvision.models.detection.transform import GeneralizedRCNNTransform

from cuas.config import DetectorSettings

# torchvision's values; changing them would break the starting weights.
ASPECT_RATIOS = (2, 3)
FEATURE_MAPS = 6
IMAGE_MEAN = (0.5, 0.5, 0.5)
IMAGE_STD = (0.5, 0.5, 0.5)
CHANNEL_MAX = 255.0


@dataclass(frozen=True)
class Box:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    class_name: str


def build_model(
    settings: DetectorSettings, num_classes: int | None = None
) -> nn.Module:
    """SSDLite resized for small targets. Downloads nothing and starts with random weights.

    torchvision's defaults are 320 px input with a smallest box of about 64 px, far larger
    than a distant drone.
    """
    size = (settings.input_size, settings.input_size)
    model = ssdlite320_mobilenet_v3_large(
        weights=None,
        weights_backbone=None,
        num_classes=num_classes or len(settings.classes) + 1,
    )
    model.score_thresh = settings.min_score
    model.topk_candidates = settings.max_candidates
    model.detections_per_img = settings.max_detections
    model.anchor_generator = DefaultBoxGenerator(
        [list(ASPECT_RATIOS) for _ in range(FEATURE_MAPS)],
        scales=list(settings.anchor_scales),
    )
    model.transform = GeneralizedRCNNTransform(
        settings.input_size,
        settings.input_size,
        list(IMAGE_MEAN),
        list(IMAGE_STD),
        size_divisible=1,
        fixed_size=size,
    )
    return model


def load_starting_weights(model: nn.Module, path: Path) -> list[str]:
    """Load everything except the class head, whose shape depends on the classes."""
    state = torch.load(path, map_location="cpu", weights_only=True)
    return copy_except_class_head(model, state)


def load_trained(settings: DetectorSettings, path: Path) -> "Detector":
    """A detector from weights fine-tuned by ``scripts/train_detector.py``."""
    model = build_model(settings)
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
    return Detector(model, settings)


def copy_except_class_head(model: nn.Module, state: Mapping) -> list[str]:
    """Copy shared weights and return which were skipped."""
    own = model.state_dict()
    kept = {k: v for k, v in state.items() if k in own and own[k].shape == v.shape}
    model.load_state_dict(kept, strict=False)
    return sorted(set(own) - set(kept))


def frame_to_tensor(frame: np.ndarray) -> torch.Tensor:
    """Height x width x 3 uint8 to the 3 x height x width floats the model expects."""
    return torch.from_numpy(frame).permute(2, 0, 1).float() / CHANNEL_MAX


class Detector:
    """A trained model ready for inference on one frame at a time."""

    def __init__(self, model: nn.Module, settings: DetectorSettings) -> None:
        torch.set_num_threads(settings.threads)
        self._model = model.eval()
        self._classes = settings.classes
        self._min_score = settings.min_score

    @torch.inference_mode()
    def detect(self, frame: np.ndarray) -> list[Box]:
        output = self._model([frame_to_tensor(frame)])[0]
        keep = output["scores"] >= self._min_score
        return [
            Box(*box, score, self._classes[label - 1])
            for box, score, label in zip(
                output["boxes"][keep].tolist(),
                output["scores"][keep].tolist(),
                output["labels"][keep].tolist(),
                strict=True,
            )
        ]
