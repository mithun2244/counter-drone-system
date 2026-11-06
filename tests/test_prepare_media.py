import importlib.util
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_media.py"
NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'


@pytest.fixture
def module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prepare_media", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_spreadsheet_is_read_with_shared_strings_and_numbers(
    module: ModuleType, tmp_path: Path
) -> None:
    path = tmp_path / "book.xlsx"
    strings = (
        f"<sst {NS}><si><t>SENSOR</t></si><si><t>NUMBER</t></si>"
        "<si><t>DISTANCE  BIN</t></si><si><t>IR</t></si><si><t>CLOSE</t></si></sst>"
    )
    sheet = (
        f"<worksheet {NS}><sheetData>"
        '<row><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
        '<c r="C1" t="s"><v>2</v></c></row>'
        '<row><c r="A2" t="s"><v>3</v></c><c r="B2"><v>7</v></c>'
        '<c r="C2" t="s"><v>4</v></c></row>'
        "</sheetData></worksheet>"
    )
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("xl/sharedStrings.xml", strings)
        book.writestr("xl/worksheets/sheet1.xml", sheet)
    assert module.read_description(path) == [
        {"SENSOR": "IR", "NUMBER": "7", "DISTANCE BIN": "CLOSE"}
    ]


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            {"SENSOR": "IR", "CLASS": "DRONE", "NUMBER": "1"},
            "svanstrom/Data/Video_IR/IR_DRONE_001.mp4",
        ),
        (
            {"SENSOR": "V", "CLASS": "BIRD", "NUMBER": "42.0"},
            "svanstrom/Data/Video_V/V_BIRD_042.mp4",
        ),
    ],
)
def test_video_path_follows_the_dataset_naming(
    module: ModuleType, row: dict[str, str], expected: str
) -> None:
    assert module.video_path(row) == expected


def test_internet_clips_are_excluded_from_splits(module: ModuleType) -> None:
    row = {
        "SENSOR": "V",
        "CLASS": "HELICOPTER",
        "NUMBER": "1",
        "DISTANCE BIN": "CLOSE",
        "DRONE TYPE / INTERNET SOURCE": "https://www.youtube.com/user/SK678387",
    }
    settings = module.load_site(module.CONFIG_DIR).station_ai.split
    entries, excluded = module.build_video([row], settings, {})
    assert entries == []
    assert excluded == [
        {
            "path": "svanstrom/Data/Video_V/V_HELICOPTER_001.mp4",
            "reason": module.EXCLUDED_VIDEO_REASON,
        }
    ]
