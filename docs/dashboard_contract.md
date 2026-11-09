# Dashboard contract, version 1

> What the backend sends the dashboard, and what the dashboard may ask of it. The dashboard is built against this contract alone; the backend never depends on how it is drawn.

**Sources of truth**

| File | What it is |
| --- | --- |
| `src/cuas/dashboard/contract.py` | The Pydantic models. The one source of truth |
| `docs/dashboard_contract.schema.json` | JSON Schema generated from the models. A test fails if it drifts. Regenerate with `uv run python scripts/record_stream.py --schema` |
| `docs/samples/*.jsonl` | Sample streams, one message per line, in the order a client receives them |

**Changes:** any change after version 1 bumps `contract` and is agreed by both sides first.

## Transport

- **Stream:** a WebSocket at `/ws`. Every message is one JSON text frame. Clients send nothing on it.
- **Actions:** HTTP JSON under `/api/` (below).
- **Where:** the server binds to `127.0.0.1` only. Every asset is served locally; the dashboard must load nothing from the internet (`docs/mapping.md`). The API documentation pages (`/docs`, `/redoc`, `/openapi.json`) are off, because they load assets from a CDN.

**Mount paths**

| Path | What |
| --- | --- |
| `/` | The operator dashboard, served from `src/cuas/dashboard/static/app/`. Until `index.html` exists there, `/` redirects to `/reference/` |
| `/reference/` | The reference page, from `src/cuas/dashboard/static/reference/`. It checks the contract end to end and is kept separate from the dashboard |
| `/ws` | The stream |
| `/api/...` | The HTTP API |

**Run it:**
- **Live:** `uv run python scripts/run_demo.py --dashboard`, then open `http://127.0.0.1:8000/`. Pick a site profile and scenario and start monitoring: the simulator plays the scenario as the live sensor feed, in real time. Each run gets a fresh folder, `runs/<scenario>_seed<seed>_<NNN>/`, and the run ID is its name. It holds the run's evidence: `evidence/chain.jsonl`, the alert snapshots beside it, the hand-off packages in `handoff/` and, with recorded media, the recordings. Check it with `uv run cuas verify runs/<run_id>`. When a run ends, the server console prints its control digest, the same one `run_demo.py --scenario ... --fast` prints for that scenario, seed and zoom setting.
- **Replay:** `uv run python scripts/run_demo.py --dashboard --replay docs/samples/s1_seed1001.jsonl` serves a sample through the same server. Start the run the sample holds (S1 at the processing plant). Pause and speed work; the run ends when the sample does.

## Conventions

- **Positions:** local ENU metres. x is east, y is north, and the origin is the site centre. Draw north up. The basemap, if any, comes in the same metres (below, and `docs/mapping.md`).
- **Angles:** degrees. Azimuth 0 is north and runs clockwise.
- **Times:** simulated seconds from the start of the run.
- **Numbers:** rounded to 3 decimal places when sent (1 mm, 0.001°, 1 ms, 0.001 probability).
- **Envelope:** every server message has `"contract": 1` and a `"type"`.
- **Order:** lists are in a meaningful order where noted. Never re-sort `alerts`.

## Message sequence

```
connect ──> hello                       profiles; the current run and latest frame, if any
operator starts a run (POST /api/runs)
        ──> run   (state "running")     the site map comes with it
        ──> frame, frame, frame ...     every 0.4 s of simulated time
        ──> evidence ...                whenever a record is written
        ──> run   (state "paused" / "running", or a new speed)
        ──> run   (state "ended")
```

A client that connects mid-run gets `hello` with `run` and the latest `frame`, so it can draw at once.

## Server messages

### `hello`

| Field | Meaning |
| --- | --- |
| `profiles` | The saved site profiles the operator can pick. Each has `profile_id`, `venue`, `zone_labels` and the `scenarios` that run there, each with `scenario_id` and `title` |
| `run` | The current run, as in `run` below, or null when idle |
| `frame` | The latest frame, or null |

### `run`

**Fields:** `run_id`, `profile_id`, `scenario_id`, `title`, `venue`, `seed`, `duration_s`, `recorded_media`, `zoom_per_station`, `state`, `speed` and `site`.
- `state` is `running`, `paused` or `ended`.
- `speed` is simulated seconds per wall second: 1, 2 or 5.

**`site`, the map:**

| Field | Meaning |
| --- | --- |
| `frame` | The coordinate frame, in words |
| `bounds` | `min_x`, `min_y`, `max_x`, `max_y`: the area to fit, margin included |
| `zones` | `zone_id`, display `label`, `weight` (critical 1.0) and `polygon` as `[x, y]` points. **Outermost first**, so drawing in order leaves the critical zone on top |
| `stations` | `station_id`, `x`, `y`, `z`. Draw as squares |
| `pickets` | `picket_id`, `x`, `y`. Draw as small dots on the outer ring |

Draw the scale bar and north arrow yourself.

### `frame`

A full snapshot every 0.4 s of simulated time: 2.5 a second at 1× speed, which meets `prd.md` FR-11's minimum of 2. Each frame replaces the last, so nothing needs to be merged. `t` never goes back. In a live run, a frame can repeat the last `t`: it is sent again whenever an evidence record is written, so a label shows even while paused. In a live run, a frame goes out one 0.2 s tick after its mark, and can show the control layer's state up to one 0.2 s batch behind.

| Field | Meaning |
| --- | --- |
| `t` | Simulated time of the snapshot |
| `tracks` | Live tracks, sorted by `track_id` |
| `alerts` | **Ranked queue, in this order:** level, then time to impact, then score, as the threat ranking published it |
| `pre_alerts` | Heard but not placed: picket or station-microphone wedges |
| `pickets_heard` | `picket_id` and `t` for picket alerts in the last 3 s. Flash those pickets |
| `rays` | Bearings from the latest batch, for the bearing-ray overlay: `station_id`, `sensor`, `azimuth_deg`, `elevation_deg`, `sigma_deg` |
| `zoom` | Each zoom camera's current task: `station_id`, `camera_id`, `track_id`, `azimuth_deg`, `elevation_deg` |
| `coverage` | `pct`, `warning`, and `reach_m` per station; null until the first figure |
| `sensors` | `sensor_id` (for example `st1.rgb` or `pk3`), `ok`, `visibility` |
| `evidence_head` | `seq` and `record_hash` of the newest evidence record, or null |

**`tracks[]` fields:**
- `track_id`; `status`, which is `tentative` or `confirmed`.
- Position `x`, `y`, `z`, and ground velocity `vx`, `vy`.
- `n_stations`, and `coasting`, which is true when `n_stations` is 0 and the position is a prediction.
- `trail`: `[t, x, y]` points over the last 20 s, oldest first, at least 0.5 s apart.
- `level`, which is `red`, `amber`, `info`, or null before the first assessment; and `alert_id`.
- `p_drone`, `p_attack_drone`, `p_bird`.

Colour tracks by level, and always add a text label too, so colour is never the only signal (`design.md` B2).

**`alerts[]` fields** (one card per alert, `design.md` B3):

| Field | Meaning |
| --- | --- |
| `alert_id`, `track_id` | The alert keeps its ID if its drone is picked up again under a new track |
| `level`, `score` | `red`, `amber` or `info`. A card stays while its track is live, even if the level falls back to `info` |
| `tti_s` | Time to impact in seconds, or null. Count it down between frames if you like: it drops by about `speed` per wall second |
| `zone_id`, `zone_label`, `approach` | `approach` is `inside`, `heading_to` or `none` |
| `class_key`, `confidence` | `attack` (confidence is P(attack drone)), `drone` or `unclassified` (confidence is P(drone)). The card shows the classifier's view: an attack drone whose engine type nobody heard can show as `drone` |
| `n_stations`, `coasting` | As for tracks |
| `reasons` | Plain English sentences, for example `heading to Pitch and Stands, 21 s`. Not translation keys yet |
| `label` | `confirm`, `dismiss` or null: the operator's latest label |
| `evidence_records` | How many evidence records this alert has |
| `looks` | Recordings behind the look evidence: `source` (`st1.rgb`, `st1.thermal`, `st2.zoom`, ...), `clip_url`, and `at_s`, the approximate offset into the clip. Empty in a simulator-only run |

**`pre_alerts[]` fields:**
- `sector_id`, `sensor_id` (a picket such as `pk4`, or `st1.acoustic`)
- the origin `x`, `y`, and `bearing_deg` with `half_width_deg`, for drawing the wedge
- `compass`: `N`, `NE`, ... `NW`
- `first_t`, `last_t`, `reports`

The B4 card is "Engine heard, `compass`, unconfirmed".

**Coverage:** a site cell counts as covered when at least 2 stations reach it (`design.md` A10). `reach_m` is each station's camera reach now, so the uncovered areas can be greyed.

### `evidence`

**Fields:** `run_id`, `seq`, `kind`, `alert_id`, `t`, `record_hash`.
- `kind` is `alert`, `escalation`, `label` or `export`.
- Sent when a record joins the evidence chain: when an alert is raised and when it first turns red, for each label and export, and an export of every alert as the run ends. Live runs only; a replay sends what its file holds.

## HTTP API

Errors return `{"detail": "..."}`, always a string: `404` for an unknown alert, clip, profile or scenario, or recorded media this machine does not have; `409` if a run is already active, for control with no run, or for a label or export when no live run is going (a replay keeps no evidence, and an ended run's evidence is closed); `422` for a bad body.

| Request | Body | Returns |
| --- | --- | --- |
| `GET /api/profiles` | — | The list of profiles, as in `hello` |
| `POST /api/runs` | `profile_id`, `scenario_id`, optional `seed`, `recorded_media` (default false), `zoom_per_station` (0, 1 or 2) | The `run` message |
| `POST /api/run/control` | `action`: `pause` or `play`; or `speed` with `speed`: 1, 2 or 5 | The `run` message |
| `POST /api/alerts/{alert_id}/label` | `label`: `confirm` or `dismiss` | `alert_id`, `seq`, `record_hash` |
| `POST /api/alerts/{alert_id}/export` | — | `alert_id`, `path`, `sha256`, and the hand-off `package` (`docs/handoff.schema.json`). Every alert is also exported when the run ends |
| `GET /api/clips/{station}/{clip}` | — | The recording (H.264 MP4), for a `<video>` element. Seek to `at_s` |
| `GET /api/contract` | — | This contract's JSON Schema |
| `GET /api/basemap` | — | The display basemap in site metres (`docs/basemap.schema.json`), or `404` when this machine has none: draw the local grid then. Added after version 1 without changing any message |

## The map: basemap, one transform, fallback

The site and every position stay in local ENU metres. The basemap is already in the same metres, projected once by `scripts/fetch_basemap.py` around the anchor in `config/site.yaml` (`docs/mapping.md`). So a dashboard needs exactly one transform, ENU metres to screen, for everything it draws:

- Fit `run.site.bounds` to the canvas, north up. Before a run starts, the basemap's own `bounds` are the same box.
- Draw in this order:
  1. basemap: land as the background, then `sea`, `water`, `green`, `rail`, `roads` (`kind` sets the width), `coastline`
  2. zones, outermost first
  3. picket and acoustic wedges (`pre_alerts`)
  4. pickets, then stations
  5. tracks, with trails and velocity arrows
- Areas are lists of rings: the first ring is the outline, any others are holes. Fill them even-odd.
- Keep the basemap's `notice` ("Simulated scenario: …") and `attribution` ("© OpenStreetMap contributors (ODbL)") visible at all times, as plain text. The licence requires the attribution.
- If `GET /api/basemap` answers `404`, draw a local grid and say so, still with a "Simulated scenario" label.
- Never convert to latitude and longitude in the dashboard. The `anchor` in the basemap is for reference only.

The reference page does all of this; `static/reference/reference.js` (`drawBackground`, `paintBasemap`, `drawNotice`) is the worked example.

**State, pause and repeated frames:**
- Replace your state from each `frame`, including one that repeats the previous `t` while paused. It is sent again because an evidence record was written, and its cards carry the new `label` and `evidence_records`, and the new `evidence_head`.
- Take a track's trail from `track.trail` only. Do not append the track's position yourself on each frame, or a repeated frame adds a duplicate point. If you keep your own history, key it by `(track_id, t)`.

**Export:** label the action "Export hand-off JSON", since it saves a file. Show the saved `path` (relative to the run folder) and the `sha256` from the response.

## Operator actions: Confirm, Dismiss, Export

Captured from a real server: a live S2 run, seed 7, simulator only, paused just after its alert was raised. Hashes and times differ from run to run; the shapes do not.

**When they work:** during a live run, running or paused, for an `alert_id` the run has raised. The server knows an alert once its `alert` evidence record is written, which is within one control batch of the card first appearing. A replay, or a run that has ended, answers `409`.

**Confirm**

```http
POST /api/alerts/alert-1/label
Content-Type: application/json

{"label": "confirm"}
```

```http
HTTP/1.1 200 OK
Content-Type: application/json

{"alert_id": "alert-1", "seq": 2, "record_hash": "0dedb4c65e449575ab3f67311b89a4f51a6ff45d0e4f04440230952cce933641"}
```

`seq` and `record_hash` are the new record in the evidence chain. On `/ws` the same record arrives as an event, and a frame follows at once, even while paused, with the card's `label` set to `"confirm"` and `evidence_records` counted up:

```json
{"contract": 1, "type": "evidence", "run_id": "s2_seed7_008", "seq": 2, "kind": "label", "alert_id": "alert-1", "t": 54.6, "record_hash": "0dedb4c65e449575ab3f67311b89a4f51a6ff45d0e4f04440230952cce933641"}
```

**Dismiss** is the same request with `{"label": "dismiss"}`:

```http
POST /api/alerts/alert-1/label
Content-Type: application/json

{"label": "dismiss"}
```

```http
HTTP/1.1 200 OK
Content-Type: application/json

{"alert_id": "alert-1", "seq": 3, "record_hash": "5b2586303ac04755dd082424ca41a3007e5b1546aa320c3261f3c1588f5e0184"}
```

Labels are never overwritten or removed: each one adds a record, and the card shows the latest (`"dismiss"` here, with `evidence_records` 3). Dismissing does not remove the card or change the alert's level; the control layer decides those.

**Export** takes no body:

```http
POST /api/alerts/alert-1/export
```

```http
HTTP/1.1 200 OK
Content-Type: application/json
```

```json
{
  "alert_id": "alert-1",
  "path": "handoff/alert-1-0004.json",
  "sha256": "d69aa8c09538645d9483b62671409ab2deb04473028e826e0dac7dcbb7d40308",
  "package": {
    "mock": true,
    "note": "Mock hand-off: a JSON file only, never sent. Detect and report only.",
    "package_version": 1,
    "run_id": "s2_seed7_008",
    "exported_t": 54.6,
    "alert": {
      "alert_id": "alert-1",
      "t": 54.6,
      "track_ids": ["trk-3"],
      "level": "red",
      "highest_level": "red",
      "score": 0.784,
      "time_to_impact_s": 37.28,
      "zone_id": "critical",
      "zone_label": "Pitch and Stands",
      "reasons": ["seen hovering", "heading to Pitch and Stands, 37 s"],
      "p_drone": 0.8,
      "p_bird": 0.2,
      "p_attack_drone": 0.0,
      "last_position": {"track_id": "trk-3", "t": 54.2, "x": 149.372, "y": 150.347, "z": 59.778, "n_stations": 3},
      "track_history": [
        {"track_id": "trk-3", "t": 14.2, "x": 493.652, "y": 417.856, "z": 59.836, "n_stations": 2},
        "... 196 more points, one per published track position, shortened here ...",
        {"track_id": "trk-3", "t": 54.2, "x": 149.372, "y": 150.347, "z": 59.778, "n_stations": 3}
      ],
      "clips": []
    },
    "labels": [
      {"label": "confirm", "t": 54.6, "seq": 2},
      {"label": "dismiss", "t": 54.6, "seq": 3}
    ],
    "alert_record_hash": "5d669b56ef104e90b45434b58a80d2829b0e2b8715b1e444101a162e1b04c82b",
    "chain_head": {"seq": 3, "record_hash": "5b2586303ac04755dd082424ca41a3007e5b1546aa320c3261f3c1588f5e0184"}
  }
}
```

- **`path`** is relative to the run folder: the file is `runs/s2_seed7_008/handoff/alert-1-0004.json`. **`sha256`** is of that stored file. The `package` in the response is the same content, but its numbers are rounded to 3 decimals like everything the server sends, so hash the file, not the response.
- **`clips`** is empty in a simulator-only run. With recorded media each entry is `{"source": "st1.rgb", "file": {"path": "station_st1/<16 hex digits>.mp4", "sha256": "..."}}`.
- **`level`** is the alert's level at export; **`highest_level`** the highest it reached. An alert whose track is lost falls back to `info`.
- **`chain_head`** is the newest record before this export's own; **`alert_record_hash`** the record written when the alert was raised.
- The event `{"type": "evidence", "kind": "export", "seq": 4, ...}` follows on `/ws`. When the run ends, every alert is exported once more (`seq` 5 here, `t` 118.0).

**Errors**, captured from the same run:

| Request | Status | Body |
| --- | --- | --- |
| `POST /api/alerts/alert-99/label` with `{"label": "confirm"}` | `404` | `{"detail": "no alert 'alert-99' in this run"}` |
| `POST /api/alerts/alert-1/label` with `{"label": "maybe"}` | `422` | `{"detail": "Input should be 'confirm' or 'dismiss'"}` |
| `POST /api/alerts/alert-1/label` with `{}` | `422` | `{"detail": "Field required"}` |
| `POST /api/alerts/alert-1/label` after the run ended, or during a replay | `409` | `{"detail": "no run that keeps evidence is going"}` |

**Try it on the reference page:** start a live run, then use the Confirm, Dismiss and Export hand-off JSON buttons on any card. The page shows the reply below the controls: for an export, the saved path and its SHA-256.

## Samples

| File | Shows |
| --- | --- |
| `s1_seed1001.jsonl` | S1, the processing plant: picket flashes, wedges and pre-alerts, then three red alerts ranked by time to impact |
| `s4_seed2002.jsonl` | S4, the stadium in dust: coverage 54.8% with the warning set, and one quadcopter alert |
| `edge_states.jsonl` | **MOCK**, hand-made: all clear, a station with both cameras down and coverage reduced, a confirmed then dismissed alert with an evidence event, paused, ended. The simulator never produces these |

**Regenerate a sample:** `uv run python scripts/record_stream.py --scenario s2 [--seed N] [--recorded-media]`. Recorded-media samples reference local recordings, so they go to `runs/samples/` and are never committed.

**Replay:** `--dashboard --replay FILE` plays any sample through the real `/ws`, paced by its simulated time. A recorded-media sample's clips are served too, from the folder `record_stream.py` leaves beside it.

## Known limits of version 1

- **`reasons` are English sentences.** Arabic (`design.md` B5) will need codes.
- **Sensor faults never happen in the simulator.** Use `edge_states.jsonl` for that state.
- **`at_s` is approximate:** the frame index times the look period.
- **Labels and exports need a live run.** Once a run ends its evidence is closed, and a replay keeps none: both answer `409`.
- **The committed samples carry no evidence:** `evidence_head` is null and `evidence_records` 0. `edge_states.jsonl` (MOCK) shows a labelled alert and an evidence event.
- **Evidence can lose its newest records unnoticed.** Removing the newest record together with the file it lists leaves a valid, shorter chain, and `cuas verify` passes. See `design.md` A11.
