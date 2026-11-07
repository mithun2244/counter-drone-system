"""Reads the dataset's per-frame boxes from its MATLAB ``groundTruth`` label files.

``scipy`` exposes these objects only as an opaque byte stream, so this walks the public MAT5
element format. The layout was confirmed on all 650 files: each clip's boxes sit in its own class
cell, they barely move between frames, and they lie on visible targets.

Each frame has one cell per class, in file order, and one 8-byte value follows the last frame.
A cell holds N boxes as an N x 4 matrix stored column by column, so two boxes occupy twice the
bytes. Telling cells apart by size alone would read a two-box cell as empty.
"""

import struct
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import scipy.io as sio

from cuas.station.detector import Box

WORKSPACE_KEY = "__function_workspace__"
WORKSPACE_PREAMBLE_BYTES = 8
TAG_BYTES = 8
ALIGNMENT_BYTES = 8
MAX_TYPE = 20
MI_DOUBLE = 9
MI_MATRIX = 14
CELL_DEPTH = 5
BYTES_PER_BOX = 32
TRAILING_CELL_BYTES = 8
FILE_CLASSES = ("airplane", "bird", "drone", "helicopter")
TARGET_SCORE = 1.0


def _elements(buffer: bytes) -> Iterator[tuple[int, bytes]]:
    """Each MAT5 element's type and payload. Small elements pack their tag into 4 bytes."""
    offset, size = 0, len(buffer)
    while offset + TAG_BYTES <= size:
        small_type, small_size = struct.unpack_from("<HH", buffer, offset)
        if small_size and small_type < MAX_TYPE:
            kind, length, start = small_type, small_size, offset + TAG_BYTES // 2
        else:
            kind, length = struct.unpack_from("<II", buffer, offset)
            start = offset + TAG_BYTES
        if not 0 < kind <= MAX_TYPE or start + length > size:
            return
        yield kind, buffer[start : start + length]
        end = start + length
        offset = end + (-end % ALIGNMENT_BYTES)


def _cells(buffer: bytes, depth: int = 0) -> Iterator[bytes]:
    """The numeric payload of every cell at the depth where the frame table lives."""
    for kind, payload in _elements(buffer):
        if kind != MI_MATRIX:
            continue
        if depth < CELL_DEPTH:
            yield from _cells(payload, depth + 1)
            continue
        children = list(_elements(payload))
        if children and children[-1][0] == MI_DOUBLE:
            yield children[-1][1]


def boxes_from_workspace(buffer: bytes, frame_count: int) -> list[list[Box]]:
    """One list of boxes per frame. Raises ``ValueError`` if the layout is not as expected."""
    cells = list(_cells(buffer))
    classes = len(FILE_CLASSES)
    expected = classes * frame_count + 1
    if len(cells) != expected or len(cells[-1]) != TRAILING_CELL_BYTES:
        raise ValueError(f"found {len(cells)} cells, expected {expected}")
    frames: list[list[Box]] = []
    for index in range(frame_count):
        boxes: list[Box] = []
        for offset, name in enumerate(FILE_CLASSES):
            boxes.extend(_cell_boxes(cells[index * classes + offset], name))
        frames.append(boxes)
    return frames


def _cell_boxes(cell: bytes, class_name: str) -> list[Box]:
    if len(cell) % BYTES_PER_BOX:
        raise ValueError(f"a cell of {len(cell)} bytes is not whole boxes")
    count = len(cell) // BYTES_PER_BOX
    matrix = np.frombuffer(cell, dtype="<f8").reshape(count, 4, order="F")
    # MATLAB counts pixels from 1, and these are x, y, width, height.
    return [
        Box(x - 1, y - 1, x - 1 + width, y - 1 + height, TARGET_SCORE, class_name)
        for x, y, width, height in matrix.tolist()
    ]


def read_label_file(path: Path, frame_count: int) -> list[list[Box]]:
    workspace = sio.loadmat(str(path))[WORKSPACE_KEY].tobytes()
    return boxes_from_workspace(workspace[WORKSPACE_PREAMBLE_BYTES:], frame_count)
