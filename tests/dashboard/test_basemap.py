"""The display basemap: the projection into site metres, loading, and the endpoint."""

import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cuas.config import BasemapSettings, SiteConfig
from cuas.dashboard.basemap import (
    Anchor,
    Area,
    Basemap,
    Road,
    StaleBasemap,
    basemap_schema_text,
    load_basemap,
)
from cuas.dashboard.contract import Bounds
from cuas.dashboard.replay import ReplayLauncher
from cuas.dashboard.server import STATIC, Hub, create_app

ROOT = Path(__file__).resolve().parents[2]
EDGE = ROOT / "docs" / "samples" / "edge_states.jsonl"
SOUTHSEA = Anchor(name="Southsea Common", lat=50.783, lon=-1.096, heading_deg=0.0)


def degree_lengths(lat_deg: float) -> tuple[float, float]:
    """Metres per degree of latitude and longitude, from the standard series: an independent
    known answer for the projection."""
    phi = math.radians(lat_deg)
    north = (
        111132.92
        - 559.82 * math.cos(2 * phi)
        + 1.175 * math.cos(4 * phi)
        - 0.0023 * math.cos(6 * phi)
    )
    east = (
        111412.84 * math.cos(phi) - 93.5 * math.cos(3 * phi) + 0.118 * math.cos(5 * phi)
    )
    return north, east


def test_the_anchor_is_the_site_origin_and_north_is_up() -> None:
    assert SOUTHSEA.to_site(50.783, -1.096) == (0.0, 0.0)
    north, east = degree_lengths(50.783)
    x, y = SOUTHSEA.to_site(50.793, -1.096)
    assert x == 0.0 and y == pytest.approx(north / 100, abs=0.01)
    x, y = SOUTHSEA.to_site(50.783, -1.086)
    assert y == 0.0 and x == pytest.approx(east / 100, abs=0.01)


def test_a_turned_site_axis_turns_the_map_the_other_way() -> None:
    turned = SOUTHSEA.model_copy(update={"heading_deg": 90.0})  # site +y points east
    x, y = turned.to_site(50.783, -1.086)  # a point due east
    assert x == pytest.approx(0.0, abs=1e-9) and y > 700.0


@pytest.mark.parametrize("heading", [0.0, 30.0, 271.5])
def test_site_metres_and_latitude_longitude_round_trip(heading: float) -> None:
    anchor = SOUTHSEA.model_copy(update={"heading_deg": heading})
    for x, y in [(0.0, 0.0), (3000.0, -3000.0), (-1234.5, 2500.25)]:
        lat, lon = anchor.to_lat_lon(x, y)
        back = anchor.to_site(lat, lon)
        assert back == pytest.approx((x, y), abs=1e-3)


def settings_for(anchor: Anchor, site: SiteConfig) -> BasemapSettings:
    return site.dashboard.basemap.model_copy(
        update={
            "anchor_name": anchor.name,
            "anchor_lat": anchor.lat,
            "anchor_lon": anchor.lon,
            "heading_deg": anchor.heading_deg,
        }
    )


def small_basemap(anchor: Anchor = SOUTHSEA) -> Basemap:
    square = [
        (-10.0, -10.0),
        (10.0, -10.0),
        (10.0, 10.0),
        (-10.0, 10.0),
        (-10.0, -10.0),
    ]
    return Basemap(
        name="Portsmouth, UK",
        notice="Simulated scenario",
        attribution="© OpenStreetMap contributors (ODbL)",
        licence="ODbL 1.0",
        source="test",
        fetched="2026-11-09",
        raw_sha256="0" * 64,
        projection="test",
        anchor=anchor,
        bounds=Bounds(min_x=-100.0, min_y=-100.0, max_x=100.0, max_y=100.0),
        sea=[Area(rings=[square])],
        water=[],
        green=[],
        roads=[Road(kind="primary", line=[(0.0, 0.0), (1.23456, 50.0)])],
        rail=[],
        coastline=[],
    )


def write(data_dir: Path, settings: BasemapSettings, text: str) -> None:
    (data_dir / "basemap").mkdir(parents=True, exist_ok=True)
    (data_dir / "basemap" / settings.file).write_text(text, encoding="utf-8")


def test_loading_gives_none_without_a_file_and_the_map_with_one(
    tmp_path: Path, site: SiteConfig
) -> None:
    settings = settings_for(SOUTHSEA, site)
    assert load_basemap(tmp_path, settings) is None
    write(tmp_path, settings, small_basemap().model_dump_json())
    assert load_basemap(tmp_path, settings) == small_basemap()


def test_the_anchor_keeps_every_digit_through_the_file(
    tmp_path: Path, site: SiteConfig
) -> None:
    """Rounded to 3 decimals, 50.78497 degrees would move the site 30 m."""
    precise = SOUTHSEA.model_copy(update={"lat": 50.78497, "lon": -1.09457})
    settings = settings_for(precise, site)
    write(tmp_path, settings, small_basemap(precise).model_dump_json())
    loaded = load_basemap(tmp_path, settings)
    assert loaded is not None and loaded.anchor == precise


def test_a_map_made_around_another_anchor_or_broken_is_refused(
    tmp_path: Path, site: SiteConfig
) -> None:
    settings = settings_for(SOUTHSEA, site)
    elsewhere = SOUTHSEA.model_copy(update={"lat": 50.80})
    write(tmp_path, settings, small_basemap(elsewhere).model_dump_json())
    with pytest.raises(StaleBasemap, match="fetch it again"):
        load_basemap(tmp_path, settings)
    write(tmp_path, settings, "{not json")
    with pytest.raises(StaleBasemap, match="not a basemap"):
        load_basemap(tmp_path, settings)


def test_the_endpoint_serves_the_map_or_says_to_draw_the_grid(
    site: SiteConfig, tmp_path: Path
) -> None:
    launcher = ReplayLauncher(EDGE, site.simulation.tick_s)
    with TestClient(create_app(Hub(launcher), tmp_path, small_basemap())) as client:
        served = client.get("/api/basemap").json()
    assert served["notice"] == "Simulated scenario"
    assert served["roads"][0]["line"][1] == [
        1.23456,
        50.0,
    ]  # rounded when built, not again
    with TestClient(create_app(Hub(launcher), tmp_path)) as client:
        missing = client.get("/api/basemap")
    assert missing.status_code == 404
    assert missing.json() == {
        "detail": "no basemap on this machine: draw the local grid"
    }


def test_the_committed_schema_matches_the_model() -> None:
    """Regenerate with ``uv run python scripts/record_stream.py --schema``."""
    schema = (ROOT / "docs" / "basemap.schema.json").read_text(encoding="utf-8")
    assert schema == basemap_schema_text()


def test_the_reference_page_always_says_the_scenario_is_simulated() -> None:
    page = (STATIC / "reference" / "reference.js").read_text(encoding="utf-8")
    assert "Simulated scenario" in page and 'fetch("/api/basemap")' in page
