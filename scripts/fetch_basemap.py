"""Fetch the display basemap once: OpenStreetMap data around the anchor, in site metres.

One Overpass API request for the box the dashboard draws (the site map's bounds), then every
point is projected into site ENU metres around the anchor in ``config/site.yaml``
(``cuas.dashboard.basemap``), simplified, and written to ``data/basemap/``, which git ignores.
The raw response is kept beside it. ``--from-raw`` rebuilds from a kept response with no network,
for example after the anchor moves within the fetched box.

The sea is assembled from the coastline: OpenStreetMap draws coastline ways with land on the left,
so each coastline piece crossing the box, followed clockwise along the box edge to the next piece,
encloses sea. If a piece does not reach the edge, the sea is left out and only the coastline line
is drawn. A report lists where the stations and pickets land, and where the anchor's named
place really is.

Data: OpenStreetMap, ODbL 1.0. The map must show "© OpenStreetMap contributors".
"""

import argparse
import hashlib
import json
import math
import sys
import urllib.parse
import urllib.request
from collections.abc import Iterable
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from cuas.config import BasemapSettings, SiteConfig, load_site
from cuas.dashboard.basemap import (
    PROJECTION,
    XY,
    Anchor,
    Area,
    Basemap,
    Bounds,
    Line,
    Ring,
    Road,
)
from cuas.dashboard.frames import site_map
from cuas.sim.scenario import load_scenario

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR, DATA_DIR = ROOT / "config", ROOT / "data"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "cuas-demo basemap fetch (one request; offline counter-drone demo)"
TIMEOUT_S = 180
LICENCE = "ODbL 1.0"
SOURCE = "OpenStreetMap via the Overpass API"
ROAD_KINDS = ("motorway", "trunk", "primary", "secondary", "tertiary")
ON_EDGE_M = 1e-6
DECIMALS = 1  # 0.1 m


# --- geometry in site metres -------------------------------------------------------------


def simplify(line: Line, tolerance: float) -> Line:
    """Ramer-Douglas-Peucker: drop points closer than ``tolerance`` to the simplified line."""
    if len(line) < 3:
        return list(line)
    keep = {0, len(line) - 1}
    stack = [(0, len(line) - 1)]
    while stack:
        first, last = stack.pop()
        (x1, y1), (x2, y2) = line[first], line[last]
        length = math.hypot(x2 - x1, y2 - y1)
        worst, at = 0.0, None
        for i in range(first + 1, last):
            x, y = line[i]
            if length == 0.0:
                d = math.hypot(x - x1, y - y1)
            else:
                d = abs((x2 - x1) * (y1 - y) - (x1 - x) * (y2 - y1)) / length
            if d > worst:
                worst, at = d, i
        if at is not None and worst > tolerance:
            keep.add(at)
            stack += [(first, at), (at, last)]
    return [line[i] for i in sorted(keep)]


def inside_box(p: XY, box: Bounds) -> bool:
    return box.min_x <= p[0] <= box.max_x and box.min_y <= p[1] <= box.max_y


def _clip_segment(a: XY, b: XY, box: Bounds) -> tuple[XY, XY] | None:
    """Liang-Barsky: the part of segment a-b inside the box, or ``None``."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in (
        (-dx, a[0] - box.min_x),
        (dx, box.max_x - a[0]),
        (-dy, a[1] - box.min_y),
        (dy, box.max_y - a[1]),
    ):
        if p == 0.0:
            if q < 0.0:
                return None
            continue
        t = q / p
        if p < 0.0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    start = a if t0 == 0.0 else (a[0] + t0 * dx, a[1] + t0 * dy)
    end = b if t1 == 1.0 else (a[0] + t1 * dx, a[1] + t1 * dy)  # exact ends stay exact
    return start, end


def clip_line(line: Line, box: Bounds) -> list[Line]:
    """The pieces of a line inside the box, in order."""
    pieces: list[Line] = []
    current: Line = []
    for a, b in pairwise(line):
        part = _clip_segment(a, b, box)
        if part is None:
            if current:
                pieces.append(current)
                current = []
            continue
        start, end = part
        if current and current[-1] != start:
            pieces.append(current)
            current = []
        if not current:
            current = [start]
        current.append(end)
        if end != b:  # left the box
            pieces.append(current)
            current = []
    if current:
        pieces.append(current)
    return [p for p in pieces if len(p) > 1]


def join_ways(ways: Iterable[Line]) -> tuple[list[Ring], list[Line]]:
    """Join ways end to start, keeping their direction. Returns closed rings and open chains."""
    open_ways = [list(w) for w in ways if len(w) > 1]
    rings: list[Ring] = []
    chains: list[Line] = []
    while open_ways:
        chain = open_ways.pop()
        grown = True
        while grown and chain[0] != chain[-1]:
            grown = False
            for i, way in enumerate(open_ways):
                if way[0] == chain[-1]:
                    chain += open_ways.pop(i)[1:]
                    grown = True
                    break
                if way[-1] == chain[0]:
                    chain = open_ways.pop(i)[:-1] + chain
                    grown = True
                    break
        (rings if chain[0] == chain[-1] else chains).append(chain)
    return rings, chains


def join_any_direction(ways: Iterable[Line]) -> tuple[list[Ring], list[Line]]:
    """For areas: members of a multipolygon may run either way."""
    pending = [list(w) for w in ways if len(w) > 1]
    rings, chains = [], []
    while pending:
        chain = pending.pop()
        grown = True
        while grown and chain[0] != chain[-1]:
            grown = False
            for i, way in enumerate(pending):
                for candidate in (way, way[::-1]):
                    if candidate[0] == chain[-1]:
                        chain += candidate[1:]
                        pending.pop(i)
                        grown = True
                        break
                if grown:
                    break
        (rings if chain[0] == chain[-1] else chains).append(chain)
    return rings, chains


def contains(rings: list[Ring], p: XY) -> bool:
    """Even-odd: inside an odd number of rings."""
    inside = False
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=False):
            crosses = (y1 > p[1]) != (y2 > p[1])
            if crosses and p[0] < x1 + (p[1] - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def _perimeter(p: XY, box: Bounds) -> float | None:
    """Clockwise distance along the box edge from the top-left corner, or ``None`` if off it."""
    w, h = box.max_x - box.min_x, box.max_y - box.min_y
    x, y = p
    if abs(y - box.max_y) < ON_EDGE_M:
        return x - box.min_x
    if abs(x - box.max_x) < ON_EDGE_M:
        return w + (box.max_y - y)
    if abs(y - box.min_y) < ON_EDGE_M:
        return w + h + (box.max_x - x)
    if abs(x - box.min_x) < ON_EDGE_M:
        return 2 * w + h + (y - box.min_y)
    return None


def _start_outside(ring: Ring, box: Bounds) -> Ring | None:
    """The closed ring rotated to start at a point outside the box, or ``None`` if none is."""
    points = ring[:-1]
    for i, p in enumerate(points):
        if not inside_box(p, box):
            rotated = points[i:] + points[:i]
            return rotated + rotated[:1]
    return None


def sea_areas(coastline: list[Line], box: Bounds) -> list[Area] | None:
    """The sea inside the box, from coastline ways (land on their left).

    ``None`` if a coastline piece ends inside the box, so the areas cannot be closed.
    """
    rings, chains = join_ways(coastline)
    islands, crossing = [], list(chains)
    for ring in rings:
        rotated = _start_outside(ring, box)
        if rotated is None:
            islands.append(ring)
        else:
            crossing.append(rotated)
    pieces = [p for line in crossing for p in clip_line(line, box)]
    w, h = box.max_x - box.min_x, box.max_y - box.min_y
    corners = [
        (0.0, (box.min_x, box.max_y)),
        (w, (box.max_x, box.max_y)),
        (w + h, (box.max_x, box.min_y)),
        (2 * w + h, (box.min_x, box.min_y)),
    ]
    entry = [_perimeter(p[0], box) for p in pieces]
    exit_ = [_perimeter(p[-1], box) for p in pieces]
    if None in entry or None in exit_:
        return None
    if not pieces:
        whole = [c for _, c in corners]
        return [Area(rings=[whole + whole[:1], *islands])] if islands else []
    perimeter = 2 * (w + h)
    outlines: list[Ring] = []
    used: set[int] = set()
    for start in range(len(pieces)):
        if start in used:
            continue
        ring: Ring = []
        j = start
        while j not in used:
            used.add(j)
            ring += pieces[j]
            leave = exit_[j]
            k = min(range(len(pieces)), key=lambda i: (entry[i] - leave) % perimeter)
            gap = (entry[k] - leave) % perimeter
            passed = sorted(
                ((s - leave) % perimeter, c)
                for s, c in corners
                if 0.0 < (s - leave) % perimeter < gap
            )
            ring += [c for _, c in passed]
            j = k
        if j != start:
            return None
        outlines.append(ring + ring[:1])
    areas: list[list[Ring]] = [[outline] for outline in outlines]
    for island in islands:
        home = next((a for a in areas if contains(a[:1], island[0])), None)
        if home is not None:
            home.append(island)
    return [Area(rings=rings) for rings in areas]


# --- OpenStreetMap ------------------------------------------------------------------------


def query(south: float, west: float, north: float, east: float, place: str) -> str:
    box = f"({south:.6f},{west:.6f},{north:.6f},{east:.6f})"
    roads = "|".join(ROAD_KINDS)
    return f"""[out:json][timeout:{TIMEOUT_S}];
(
  way["natural"="coastline"]{box};
  way["natural"="water"]{box};
  relation["natural"="water"]{box};
  way["highway"~"^({roads})(_link)?$"]{box};
  way["railway"="rail"]{box};
  way["leisure"="park"]{box};
  relation["leisure"="park"]{box};
  way["landuse"~"^(grass|recreation_ground)$"]{box};
  way["name"="{place}"]{box};
  relation["name"="{place}"]{box};
);
out geom;
"""


def fetch(text: str, endpoint: str) -> bytes:
    body = urllib.parse.urlencode({"data": text}).encode()
    request = urllib.request.Request(
        endpoint, data=body, headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S + 30) as reply:
        return reply.read()


def _project(points: list[dict], anchor: Anchor) -> Line:
    return [anchor.to_site(p["lat"], p["lon"]) for p in points if p]


def _area_rings(element: dict, anchor: Anchor) -> list[Ring]:
    if element["type"] == "way":
        line = _project(element.get("geometry", []), anchor)
        return [line] if len(line) > 3 and line[0] == line[-1] else []
    members = [m for m in element.get("members", []) if m.get("type") == "way"]
    outer = [
        _project(m.get("geometry", []), anchor)
        for m in members
        if m.get("role") != "inner"
    ]
    inner = [
        _project(m.get("geometry", []), anchor)
        for m in members
        if m.get("role") == "inner"
    ]
    return join_any_direction(outer)[0] + join_any_direction(inner)[0]


class Layers:
    def __init__(self) -> None:
        self.coastline: list[Line] = []
        self.water: list[list[Ring]] = []
        self.green: list[list[Ring]] = []
        self.roads: list[tuple[str, Line]] = []
        self.rail: list[Line] = []
        self.place: list[Ring] = []


def sort_elements(raw: dict, anchor: Anchor, place: str) -> Layers:
    layers = Layers()
    for element in raw.get("elements", []):
        tags = element.get("tags", {})
        if tags.get("name") == place:
            layers.place += _area_rings(element, anchor)
        if tags.get("natural") == "coastline" and element["type"] == "way":
            layers.coastline.append(_project(element.get("geometry", []), anchor))
        elif tags.get("natural") == "water":
            layers.water.append(_area_rings(element, anchor))
        elif tags.get("leisure") == "park" or tags.get("landuse") in (
            "grass",
            "recreation_ground",
        ):
            layers.green.append(_area_rings(element, anchor))
        elif tags.get("highway", "").removesuffix("_link") in ROAD_KINDS:
            line = _project(element.get("geometry", []), anchor)
            layers.roads.append((tags["highway"].removesuffix("_link"), line))
        elif tags.get("railway") == "rail":
            layers.rail.append(_project(element.get("geometry", []), anchor))
    return layers


def _round(line: Line) -> Line:
    return [(round(x, DECIMALS), round(y, DECIMALS)) for x, y in line]


def _lines(lines: Iterable[Line], box: Bounds, tolerance: float) -> list[Line]:
    return [
        _round(simplify(p, tolerance)) for line in lines for p in clip_line(line, box)
    ]


def _areas(groups: Iterable[list[Ring]], tolerance: float) -> list[Area]:
    out = []
    for rings in groups:
        kept = [_round(simplify(r, tolerance)) for r in rings]
        kept = [r for r in kept if len(r) > 3]
        if kept:
            out.append(Area(rings=kept))
    return out


def build(
    raw_bytes: bytes, settings: BasemapSettings, box: Bounds, fetched: str, source: str
) -> tuple[Basemap, Layers]:
    anchor = Anchor.of(settings)
    layers = sort_elements(json.loads(raw_bytes), anchor, settings.anchor_name)
    tolerance = settings.simplify_m
    sea = sea_areas(layers.coastline, box)
    basemap = Basemap(
        name=settings.name,
        notice=settings.notice,
        attribution=settings.attribution,
        licence=LICENCE,
        source=source,
        fetched=fetched,
        raw_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        projection=PROJECTION,
        anchor=anchor,
        bounds=box,
        sea=[] if sea is None else _areas((a.rings for a in sea), tolerance),
        water=_areas(layers.water, tolerance),
        green=_areas(layers.green, tolerance),
        roads=[
            Road(kind=kind, line=line)
            for kind, whole in layers.roads
            for line in _lines([whole], box, tolerance)
        ],
        rail=_lines(layers.rail, box, tolerance),
        coastline=_lines(layers.coastline, box, tolerance),
    )
    return basemap, layers


# --- report -------------------------------------------------------------------------------


def centroid(ring: Ring) -> XY:
    area = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=False):
        cross = x1 * y2 - x2 * y1
        area += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    return cx / (3 * area), cy / (3 * area)


def where(p: XY, basemap: Basemap) -> str:
    if any(contains(a.rings, p) for a in basemap.sea):
        return "in the sea"
    if any(contains(a.rings, p) for a in basemap.water):
        return "in water"
    return "on land"


def report(basemap: Basemap, layers: Layers, site: SiteConfig, size: int) -> list[str]:
    lines = [
        (
            f"basemap: {size / 1024:.0f} KB; sea {len(basemap.sea)} areas, water "
            f"{len(basemap.water)}, green {len(basemap.green)}, roads {len(basemap.roads)}, "
            f"rail {len(basemap.rail)}, coastline {len(basemap.coastline)} lines"
        )
    ]
    if not basemap.sea:
        lines.append(
            "sea: not filled (the coastline did not close in the box); coastline drawn"
        )
    anchor = basemap.anchor
    if layers.place:
        biggest = max(layers.place, key=lambda r: abs(centroid_area(r)))
        x, y = centroid(biggest)
        lat, lon = anchor.to_lat_lon(x, y)
        lines.append(
            f"{anchor.name}: OSM centroid {lat:.5f}, {lon:.5f}, which is "
            f"{math.hypot(x, y):.0f} m from the anchor ({x:+.0f} m east, {y:+.0f} m north)"
        )
    else:
        lines.append(f"{anchor.name}: not found in the fetched data")
    for kind, points in (
        ("station", [(s.id, s.position_enu_m[:2]) for s in site.stations]),
        ("picket", [(p.id, p.position_enu_m[:2]) for p in site.pickets]),
    ):
        for name, (x, y) in points:
            lines.append(
                f"{kind} {name} at ({x:.0f}, {y:.0f}) m: {where((x, y), basemap)}"
            )
    return lines


def centroid_area(ring: Ring) -> float:
    return (
        sum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=False)
        )
        / 2
    )


# --- main ---------------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--endpoint",
        default=OVERPASS_URL,
        help="Overpass API instance; another public one if the main one is busy",
    )
    parser.add_argument(
        "--from-raw",
        type=Path,
        help="rebuild from a kept Overpass response, no network",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    site = load_site(CONFIG_DIR)
    settings = site.dashboard.basemap
    labels = load_scenario(
        CONFIG_DIR, "s2"
    ).metadata.zone_labels  # bounds need no labels
    box = site_map(site, labels, site.dashboard.map_margin_fraction).bounds
    out = DATA_DIR / "basemap" / settings.file
    raw_path = out.with_suffix(".osm.json")
    if args.from_raw:
        raw = args.from_raw.read_bytes()
    else:
        anchor = Anchor.of(settings)
        south, west = anchor.to_lat_lon(box.min_x, box.min_y)
        north, east = anchor.to_lat_lon(box.max_x, box.max_y)
        print(f"fetching {settings.name} from {args.endpoint} ...")
        try:
            raw = fetch(
                query(south, west, north, east, settings.anchor_name), args.endpoint
            )
        except OSError as error:  # HTTP errors and timeouts: Overpass is often busy
            print(
                f"fetch failed: {error}. Try again in a few minutes.", file=sys.stderr
            )
            return 1
        out.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw)
    fetched = datetime.now(UTC).date().isoformat()
    where_from = (
        f"rebuilt from {args.from_raw.name}" if args.from_raw else args.endpoint
    )
    basemap, layers = build(raw, settings, box, fetched, f"{SOURCE} ({where_from})")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(basemap.model_dump_json(), encoding="utf-8")
    for line in report(basemap, layers, site, out.stat().st_size):
        print(line)
    print(f"wrote {out.relative_to(ROOT)}; raw response {raw_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
