# Mapping — the site map on the dashboard

> Decisions about the map the operator sees. Decided by the user on 2026-11-08, for Phase 5.

## Phase 5 demo: a local vector map

- **What it is:** a north-up, 2D drawing of the fictional demo site, made from `config/site.yaml` in local metres. There is no map background, no tiles and no imagery.
- **What it shows:** named zones (the critical zone darkest), stations, pickets, tracks and their trails, a scale bar and a north arrow. Optional overlays: bearing rays and station range rings.
- **Coordinates:** the local ENU frame (`architecture.md`): x east, y north, metres, origin at the site centre. The dashboard contract carries positions in this frame only.
- **Site profiles:** the operator selects a saved site profile and starts monitoring. Nothing is uploaded. A profile is the shared `site.yaml` geometry plus a venue's display labels, from scenario metadata: "Fictional Processing Plant" (S1) and "Fictional Stadium" (S2, S3, S4). In the demo, "start monitoring" replays a scenario as the live sensor feed.
- **Offline-first:** the dashboard loads nothing from the internet. There are no CDN scripts, web fonts, tiles or external URLs, and the API's own documentation pages are turned off because they load assets from a CDN. It is verified from a cold start with the internet disconnected.
- **Why:** the site is fictional, so a real map would place it somewhere real, and `rules.md` keeps real site data out of this repo. A drawing from `site.yaml` works offline by construction.

## Production direction (not built in the demo)

- **Map engine:** MapLibre GL JS, with self-hosted PMTiles. Tiles are served by the system itself, not fetched from a third party.
- **Base map:** a surveyed site map approved by the client. Online imagery is optional, where the client allows it.
- **Georeferencing:** a surveyed site origin (latitude, longitude, height and grid heading) turns ENU metres into map coordinates in the frontend. The backend keeps working in ENU metres.
- **Independence:** tracking, alerts and evidence never depend on the map background. A missing, slow or wrong background changes only what is drawn under the tracks, never a track, an alert or a record.

## Still open

- Where production tiles and imagery are hosted, given that client data stays in the Kingdom (`rules.md` §5).
- The base-map source and its licence. OpenStreetMap data, for example, needs ODbL attribution.
- The datum and grid used for the site survey.
