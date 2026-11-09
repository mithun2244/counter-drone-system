"""The display basemap: real map data turned into site ENU metres, once (docs/mapping.md).

The fictional site keeps its own coordinates. ``scripts/fetch_basemap.py`` projects map data
around an anchor, the point where the site's origin is drawn, so every frontend draws basemap,
zones, sensors, wedges and tracks through one ENU-to-screen transform and never handles latitude
or longitude. Nothing here reaches tracking, alerts or evidence.

Projection: a local plane at the anchor, scaled by the WGS84 meridian and prime-vertical radii
there. Within 4 km of the anchor it differs from true ENU by under 2 m, mostly from the meridians
converging: a third of a pixel on a 7 km map drawn 1,000 pixels wide.
"""

import json
import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from cuas.config import BasemapSettings
from cuas.dashboard.contract import XY, Bounds

WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
E2 = WGS84_F * (2 - WGS84_F)
PROJECTION = "local plane at the anchor, WGS84 radii there; x east, y north, metres"

Ring = list[XY]
Line = list[XY]


def radii(lat_deg: float) -> tuple[float, float]:
    """Meridian and prime-vertical radii of curvature, metres."""
    s = math.sin(math.radians(lat_deg))
    w = math.sqrt(1 - E2 * s * s)
    return WGS84_A * (1 - E2) / w**3, WGS84_A / w


class MapModel(BaseModel):
    """Not rounded when sent, unlike the contract's models: map coordinates are rounded to
    0.1 m when the map is built, and the anchor must keep every digit."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Anchor(MapModel):
    name: str
    lat: float
    lon: float
    heading_deg: float
    """True bearing of the site's +y axis."""

    def to_site(self, lat: float, lon: float) -> XY:
        meridian, normal = radii(self.lat)
        east = math.radians(lon - self.lon) * normal * math.cos(math.radians(self.lat))
        north = math.radians(lat - self.lat) * meridian
        h = math.radians(self.heading_deg)
        return (
            east * math.cos(h) - north * math.sin(h),
            east * math.sin(h) + north * math.cos(h),
        )

    def to_lat_lon(self, x: float, y: float) -> tuple[float, float]:
        """The inverse of ``to_site``: for reports and the fetch box, never for drawing."""
        h = math.radians(self.heading_deg)
        east, north = (
            x * math.cos(h) + y * math.sin(h),
            -x * math.sin(h) + y * math.cos(h),
        )
        meridian, normal = radii(self.lat)
        lat = self.lat + math.degrees(north / meridian)
        lon = self.lon + math.degrees(
            east / (normal * math.cos(math.radians(self.lat)))
        )
        return lat, lon

    @classmethod
    def of(cls, settings: BasemapSettings) -> "Anchor":
        return cls(
            name=settings.anchor_name,
            lat=settings.anchor_lat,
            lon=settings.anchor_lon,
            heading_deg=settings.heading_deg,
        )


class Area(MapModel):
    """Rings in site metres: the first is the outline, any others are holes (draw even-odd)."""

    rings: list[Ring]


class Road(MapModel):
    kind: str
    """``motorway``, ``trunk``, ``primary``, ``secondary`` or ``tertiary``."""
    line: Line


class Basemap(MapModel):
    name: str
    notice: str
    """Show on the map at all times."""
    attribution: str
    """Show on the map at all times: the data's licence requires it."""
    licence: str
    source: str
    fetched: str
    """UTC date of the fetch."""
    raw_sha256: str
    """Of the raw response kept beside the file."""
    projection: str
    anchor: Anchor
    bounds: Bounds
    sea: list[Area]
    """Empty if the coastline could not be closed into areas: draw ``coastline`` alone then."""
    water: list[Area]
    green: list[Area]
    roads: list[Road]
    rail: list[Line]
    coastline: list[Line]


class StaleBasemap(Exception):
    """The basemap file does not match the configured anchor, or does not parse."""


def load_basemap(data_dir: Path, settings: BasemapSettings) -> Basemap | None:
    """The basemap, or ``None`` if none was fetched: frontends then draw the local grid.

    Raises ``StaleBasemap`` for a file that does not parse or was made around another anchor,
    so a wrong map is never drawn under the site.
    """
    path = data_dir / "basemap" / settings.file
    if not path.is_file():
        return None
    try:
        basemap = Basemap.model_validate_json(path.read_bytes())
    except ValueError as error:
        raise StaleBasemap(f"{path} is not a basemap: {error}") from error
    if basemap.anchor != Anchor.of(settings):
        raise StaleBasemap(
            f"{path} was made around {basemap.anchor}, not the configured anchor; "
            "fetch it again with scripts/fetch_basemap.py"
        )
    return basemap


def basemap_schema_text() -> str:
    """``docs/basemap.schema.json``, generated from the model."""
    schema = Basemap.model_json_schema()
    return json.dumps(schema, indent=1, sort_keys=True) + "\n"
