import struct

import numpy as np
import pytest

from cuas.metrics.mat_labels import (
    CELL_DEPTH,
    FILE_CLASSES,
    MI_DOUBLE,
    MI_MATRIX,
    TRAILING_CELL_BYTES,
    boxes_from_workspace,
)


def element(kind: int, payload: bytes) -> bytes:
    padding = b"\0" * (-len(payload) % 8)
    return struct.pack("<II", kind, len(payload)) + payload + padding


def boxes_cell(*boxes: tuple[float, float, float, float]) -> bytes:
    """A class cell holding these boxes, stored column by column as MATLAB does."""
    if not boxes:
        return b""
    return (
        np.array(boxes, dtype="<f8").reshape(len(boxes), 4).ravel(order="F").tobytes()
    )


def workspace(cells: list[bytes]) -> bytes:
    """Cells wrapped at the depth where the real label files keep them."""
    inner = b"".join(element(MI_MATRIX, element(MI_DOUBLE, cell)) for cell in cells)
    for _ in range(CELL_DEPTH):
        inner = element(MI_MATRIX, inner)
    return inner


def frame(**by_class: list[tuple[float, float, float, float]]) -> list[bytes]:
    return [boxes_cell(*by_class.get(name, [])) for name in FILE_CLASSES]


def trailer() -> bytes:
    return b"\0" * TRAILING_CELL_BYTES


def test_each_box_is_converted_from_matlab_coordinates_with_its_class() -> None:
    cells = [*frame(drone=[(11.0, 21.0, 5.0, 4.0)]), trailer()]
    [[box]] = boxes_from_workspace(workspace(cells), 1)
    assert (box.x1, box.y1, box.x2, box.y2) == (10.0, 20.0, 15.0, 24.0)
    assert box.class_name == "drone"


def test_frames_and_classes_land_in_the_right_place() -> None:
    cells = [
        *frame(bird=[(1.0, 1.0, 2.0, 2.0)]),
        *frame(airplane=[(3.0, 3.0, 2.0, 2.0)]),
        trailer(),
    ]
    first, second = boxes_from_workspace(workspace(cells), 2)
    assert [b.class_name for b in first] == ["bird"]
    assert [b.class_name for b in second] == ["airplane"]


def test_a_two_box_cell_is_two_boxes_not_an_empty_frame() -> None:
    """A third-party decoder treated this cell's size as an empty frame."""
    two = [(155.0, 15.0, 14.0, 10.0), (137.0, 163.0, 10.0, 9.0)]
    cells = [*frame(drone=two), trailer()]
    [boxes] = boxes_from_workspace(workspace(cells), 1)
    assert [(b.x1, b.y1) for b in boxes] == [(154.0, 14.0), (136.0, 162.0)]


def test_a_frame_with_no_target_has_no_boxes() -> None:
    assert boxes_from_workspace(workspace([*frame(), trailer()]), 1) == [[]]


def test_a_frame_can_hold_two_classes() -> None:
    cells = [
        *frame(bird=[(1.0, 1.0, 2.0, 2.0)], drone=[(9.0, 9.0, 2.0, 2.0)]),
        trailer(),
    ]
    [boxes] = boxes_from_workspace(workspace(cells), 1)
    assert {b.class_name for b in boxes} == {"bird", "drone"}


def test_the_wrong_frame_count_is_refused() -> None:
    with pytest.raises(ValueError, match="cells"):
        boxes_from_workspace(workspace([*frame(), trailer()]), 2)


def test_a_cell_that_is_not_whole_boxes_is_refused() -> None:
    cells = [*frame(), trailer()]
    cells[2] = b"\0" * 40
    with pytest.raises(ValueError, match="whole boxes"):
        boxes_from_workspace(workspace(cells), 1)


def test_a_small_element_tag_is_read() -> None:
    small = struct.pack("<HH", MI_DOUBLE, 8) + b"\0" * 8
    matrix = element(MI_MATRIX, small)
    inner = matrix * 5  # four class cells, then the trailing value
    for _ in range(CELL_DEPTH):
        inner = element(MI_MATRIX, inner)
    with pytest.raises(ValueError, match="whole boxes"):
        boxes_from_workspace(inner, 1)
