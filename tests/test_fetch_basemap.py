"""The basemap fetch script's geometry and parsing, on hand-made data: no network."""

import importlib.util
import json
from itertools import pairwise
from pathlib import Path
from types import ModuleType

import pytest

from cuas.config import SiteConfig
from cuas.dashboard.basemap import Anchor
from cuas.dashboard.contract import Bounds

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fetch_basemap.py"
BOX = Bounds(min_x=-100.0, min_y=-100.0, max_x=100.0, max_y=100.0)


@pytest.fixture
def fb() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fetch_basemap", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def area(ring) -> float:
    pairs = pairwise(ring)
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in pairs) / 2


def test_simplify_keeps_corners_and_drops_near_straight_points(fb: ModuleType) -> None:
    line = [(0.0, 0.0), (10.0, 0.5), (20.0, 0.0), (20.0, 20.0)]
    assert fb.simplify(line, 1.0) == [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0)]
    assert fb.simplify(line, 0.1) == line


def test_clipping_keeps_the_inside_and_exact_ends(fb: ModuleType) -> None:
    through = [(-150.0, 0.0), (0.1, 0.0), (0.3, 0.0), (150.0, 0.0)]
    assert fb.clip_line(through, BOX) == [
        [(-100.0, 0.0), (0.1, 0.0), (0.3, 0.0), (100.0, 0.0)]
    ]
    out_and_in = [(-50.0, 0.0), (-50.0, 200.0), (50.0, 200.0), (50.0, 0.0)]
    assert fb.clip_line(out_and_in, BOX) == [
        [(-50.0, 0.0), (-50.0, 100.0)],
        [(50.0, 100.0), (50.0, 0.0)],
    ]


def test_ways_join_end_to_start_into_chains_and_rings(fb: ModuleType) -> None:
    rings, chains = fb.join_ways(
        [[(0, 0), (1, 0)], [(1, 0), (1, 1)], [(5, 5), (6, 5)], [(1, 1), (0, 0)]]
    )
    assert rings == [[(0, 0), (1, 0), (1, 1), (0, 0)]] or len(rings[0]) == 4
    assert chains == [[(5, 5), (6, 5)]]


def test_the_sea_is_on_the_right_of_the_coastline(fb: ModuleType) -> None:
    west_to_east = [[(-200.0, 0.0), (200.0, 0.0)]]  # land on the left: north
    (sea,) = fb.sea_areas(west_to_east, BOX)
    assert len(sea.rings) == 1
    outline = sea.rings[0]
    assert max(y for _, y in outline) == 0.0 and min(y for _, y in outline) == -100.0
    assert area(outline) == pytest.approx(-20000.0)  # clockwise, half the box
    (other_side,) = fb.sea_areas([[(200.0, 0.0), (-200.0, 0.0)]], BOX)
    assert min(y for _, y in other_side.rings[0]) == 0.0


def test_a_coast_round_a_corner_takes_the_corner(fb: ModuleType) -> None:
    corner = [[(-200.0, 50.0), (50.0, 50.0), (50.0, -200.0)]]  # land to the north-east
    (sea,) = fb.sea_areas(corner, BOX)
    assert (-100.0, -100.0) in sea.rings[0] and (100.0, 100.0) not in sea.rings[0]
    assert fb.contains(sea.rings, (0.0, 0.0)) and not fb.contains(
        sea.rings, (75.0, 75.0)
    )


def test_an_island_is_a_hole_in_the_sea(fb: ModuleType) -> None:
    coast = [[(-200.0, 50.0), (200.0, 50.0)]]  # sea south of y = 50
    island = [
        (-10.0, -10.0),
        (10.0, -10.0),
        (10.0, 10.0),
        (-10.0, 10.0),
        (-10.0, -10.0),
    ]
    (sea,) = fb.sea_areas([*coast, island], BOX)
    assert len(sea.rings) == 2
    assert not fb.contains(sea.rings, (0.0, 0.0))
    assert fb.contains(sea.rings, (0.0, -50.0))


def test_an_island_alone_makes_the_whole_box_sea_but_the_island(fb: ModuleType) -> None:
    island = [
        (-10.0, -10.0),
        (10.0, -10.0),
        (10.0, 10.0),
        (-10.0, 10.0),
        (-10.0, -10.0),
    ]
    (sea,) = fb.sea_areas([island], BOX)
    assert fb.contains(sea.rings, (50.0, 50.0)) and not fb.contains(
        sea.rings, (0.0, 0.0)
    )


def test_a_coastline_ending_inside_the_box_leaves_the_sea_unfilled(
    fb: ModuleType,
) -> None:
    assert fb.sea_areas([[(-200.0, 0.0), (0.0, 0.0)]], BOX) is None
    assert fb.sea_areas([], BOX) == []


def canned_response(anchor: Anchor) -> bytes:
    """A tiny Overpass answer: a coast across the box, a road, a park, the anchor's place."""

    def geometry(points):
        return [
            dict(zip(("lat", "lon"), anchor.to_lat_lon(x, y), strict=True))
            for x, y in points
        ]

    park = [(-30.0, 10.0), (30.0, 10.0), (30.0, 40.0), (-30.0, 40.0), (-30.0, 10.0)]
    elements = [
        {
            "type": "way",
            "tags": {"natural": "coastline"},
            "geometry": geometry([(-5000.0, -200.0), (5000.0, -200.0)]),
        },
        {
            "type": "way",
            "tags": {"highway": "primary_link"},
            "geometry": geometry([(0.0, -5000.0), (0.0, 5000.0)]),
        },
        {
            "type": "way",
            "tags": {"leisure": "park", "name": anchor.name},
            "geometry": geometry(park),
        },
        {"type": "way", "tags": {"building": "yes"}, "geometry": geometry(park)},
    ]
    return json.dumps({"elements": elements}).encode()


def test_a_canned_response_builds_a_valid_basemap_and_a_report(
    fb: ModuleType, site: SiteConfig
) -> None:
    settings = site.dashboard.basemap
    anchor = Anchor.of(settings)
    box = Bounds(min_x=-3600.0, min_y=-3600.0, max_x=3600.0, max_y=3600.0)
    raw = canned_response(anchor)
    basemap, layers = fb.build(raw, settings, box, "2026-11-09", "test")
    assert basemap.anchor == anchor and basemap.notice == settings.notice
    assert [r.kind for r in basemap.roads] == ["primary"]
    assert basemap.roads[0].line == [(0.0, -3600.0), (0.0, 3600.0)]
    assert len(basemap.green) == 1 and len(basemap.sea) == 1
    assert fb.contains(basemap.sea[0].rings, (0.0, -3000.0))  # south of the coast
    lines = fb.report(basemap, layers, site, 1024)
    place = next(line for line in lines if line.startswith(settings.anchor_name))
    assert "25 m from the anchor" in place and "+25 m north" in place
    assert "picket pk5 at (0, -3000) m: in the sea" in lines
    assert "picket pk1 at (0, 3000) m: on land" in lines
