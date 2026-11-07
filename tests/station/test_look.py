import inspect

import numpy as np
import pytest

from cuas.config import SiteConfig
from cuas.station import confirm, detector, local_tracker, look
from cuas.station.detector import Box
from cuas.station.look import CachedDetector, LookStream

CLASSES = ("drone", "bird")
WIDTH = 1000
HIGH = 0.5
FORBIDDEN = {"label", "target", "target_id", "target_type", "path", "class_id"}
WEIGHTS_LOADERS = {"load_starting_weights", "load_trained"}


def drone(x: float, score: float = 0.9, name: str = "drone") -> Box:
    return Box(x - 2, 10, x + 2, 14, score, name)


@pytest.fixture
def stream(site: SiteConfig) -> LookStream:
    return LookStream(site.station_ai.look, CLASSES, HIGH, WIDTH)


def test_every_class_is_always_reported(stream: LookStream) -> None:
    assert stream.update([]) == {"drone": 0.0, "bird": 0.0}


def test_an_unconfirmed_target_reports_zero(stream: LookStream) -> None:
    assert stream.update([drone(0)]) == {"drone": 0.0, "bird": 0.0}
    assert stream.update([drone(5)]) == {"drone": 0.0, "bird": 0.0}


def test_a_confirmed_target_reports_its_average_confidence(stream: LookStream) -> None:
    stream.update([drone(0, 0.6)])
    stream.update([drone(5, 0.8)])
    result = stream.update([drone(10, 1.0)])
    assert result == pytest.approx({"drone": 0.8, "bird": 0.0})


def test_a_single_frame_of_noise_never_confirms(stream: LookStream) -> None:
    results = [stream.update([drone(0)]), stream.update([]), stream.update([])]
    assert all(r == {"drone": 0.0, "bird": 0.0} for r in results)


def test_a_track_not_seen_in_this_frame_reports_zero(stream: LookStream) -> None:
    for x in (0, 5, 10):
        stream.update([drone(x)])
    assert stream.update([]) == {"drone": 0.0, "bird": 0.0}


def test_low_confidence_boxes_alone_never_confirm(stream: LookStream) -> None:
    results = [stream.update([drone(x, score=0.2)]) for x in range(8)]
    assert all(r == {"drone": 0.0, "bird": 0.0} for r in results)


def test_cached_detector_runs_once_per_frame_key() -> None:
    calls: list[int] = []

    def detect(frame: np.ndarray) -> list[Box]:
        calls.append(1)
        return [drone(1)]

    cached = CachedDetector(detect)
    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    first = cached.boxes("abc:7", frame)
    assert cached.boxes("abc:7", frame) == first
    assert len(calls) == 1
    cached.boxes("abc:8", frame)
    assert len(calls) == 2


@pytest.mark.parametrize("module", [look, confirm, detector, local_tracker])
def test_station_code_has_no_parameter_for_a_label_path_or_target(module) -> None:
    for name, item in vars(module).items():
        if getattr(item, "__module__", None) != module.__name__:
            continue
        functions = [item] if inspect.isfunction(item) else []
        if inspect.isclass(item):
            functions = [f for _, f in inspect.getmembers(item, inspect.isfunction)]
        for function in functions:
            parameters = set(inspect.signature(function).parameters)
            bad = parameters & FORBIDDEN
            if name in WEIGHTS_LOADERS:
                bad -= {"path"}  # the weights file, which is not a clip
            assert not bad, f"{module.__name__}.{function.__qualname__}: {bad}"
