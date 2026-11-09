# Mapping — the site map on the dashboard

> Decisions about the map the operator sees. Decided by the user on 2026-11-08 for Phase 5, and changed by the user on 2026-11-09 to the Portsmouth basemap below.

## Phase 5 demo: the fictional site drawn over Portsmouth, UK

Changed by the user on 2026-11-09. The first Phase 5 decision had no map background, because "a real map would place the site somewhere real". The user chose a real basemap for the operator display, with the site and its threats kept fictional and labelled as simulated.

- **What it is:** the fictional site from `config/site.yaml`, in its own local metres, drawn over an OpenStreetMap basemap of Portsmouth, UK. North is up, in 2D, with named zones, stations, pickets, acoustic wedges, tracks and trails, a scale bar and a north arrow.
- **Always visible:** "Simulated scenario: fictional site and threats drawn over Portsmouth, UK", and "© OpenStreetMap contributors (ODbL)".
- **Anchor:** the site's ENU origin is drawn at 50.78497° N, 1.09457° W, north up (`site.yaml`, `dashboard.basemap`). That is the OpenStreetMap centroid of Southsea Common (50.78425° N, 1.09457° W), moved 80 m north so that all three stations sit on land. It was approved by the user after the fetch report.
- **Where things fall:** stations st1–st3 on the Common. Pickets pk4, pk5, pk6 and pk7 in the water: the Solent and, for pk7, just off Gosport. pk1, pk2, pk3 and pk8 on land.
- **One transform:** `scripts/fetch_basemap.py` converts the map data from latitude and longitude into site metres once, around the anchor (`cuas.dashboard.basemap`). Frontends then draw basemap, zones, sensors, wedges and tracks through the same ENU-to-screen transform, and never handle latitude or longitude.
  - Projection: a local plane at the anchor with the WGS84 radii there. Within 4 km it differs from true ENU by under 2 m: a third of a pixel at this scale.
- **Fallback:** without a fetched basemap, `GET /api/basemap` answers `404`, and frontends draw a 500 m local grid with the notice "Simulated scenario: fictional site · local grid 500 m (no basemap)". A basemap made around a different anchor stops the server at start, so a wrong map is never drawn under the site.
- **Offline-first:** the basemap is fetched once, into `data/basemap/` (not committed), and served by the dashboard server. Nothing is loaded from the internet at run time. A fresh clone shows the local grid until `uv run python scripts/fetch_basemap.py` is run.
- **Site profiles:** unchanged. The operator selects a saved site profile and starts monitoring, with nothing uploaded. "Fictional Processing Plant" (S1) and "Fictional Stadium" (S2, S3, S4) share the geometry and the basemap.
- **Independence:** tracking, alerts and evidence never use the basemap. A missing, stale or wrong basemap changes only what is drawn.

## Production direction (not built in the demo)

- **Map engine:** MapLibre GL JS, with self-hosted PMTiles. Tiles are served by the system itself, not fetched from a third party.
- **Base map:** a surveyed site map approved by the client. Online imagery is optional, where the client allows it.
- **Georeferencing:** a surveyed site origin (latitude, longitude, height and grid heading) turns ENU metres into map coordinates in the frontend. The backend keeps working in ENU metres.
- **Independence:** tracking, alerts and evidence never depend on the map background. A missing, slow or wrong background changes only what is drawn under the tracks, never a track, an alert or a record.

## Still open

- Where production tiles and imagery are hosted, given that client data stays in the Kingdom (`rules.md` §5).
- The production base-map source and its licence. The demo uses OpenStreetMap under ODbL (`data/README.md`); a client map may not.
- The datum and grid used for the site survey.
