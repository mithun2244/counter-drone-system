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
- **Live:** `uv run python scripts/run_demo.py --dashboard`, then open `http://127.0.0.1:8000/`. Pick a site profile and scenario and start monitoring: the simulator plays the scenario as the live sensor feed, in real time. Each run gets a fresh folder, `runs/<scenario>_seed<seed>_<NNN>/`, and the run ID is its name. When a run ends, the server console prints its control digest, the same one `run_demo.py --scenario ... --fast` prints for that scenario, seed and zoom setting.
- **Replay:** `uv run python scripts/run_demo.py --dashboard --replay docs/samples/s1_seed1001.jsonl` serves a sample through the same server. Start the run the sample holds (S1 at the processing plant). Pause and speed work; the run ends when the sample does.

## Conventions

- **Positions:** local ENU metres. x is east, y is north, and the origin is the site centre. Draw north up. There is no map background (`docs/mapping.md`).
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

A full snapshot every 0.4 s of simulated time: 2.5 a second at 1× speed, which meets `prd.md` FR-11's minimum of 2. Each frame replaces the last, so nothing needs to be merged. In a live run, a frame goes out one 0.2 s tick after its mark, and can show the control layer's state up to one 0.2 s batch behind.

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
- Sent when a record joins the evidence chain.

## HTTP API

Served now, except label and export, which arrive with the evidence store (step 6). Errors return `{"detail": "..."}`, always a string: `404` for an unknown alert, clip, profile or scenario, or recorded media this machine does not have; `409` if a run is already active, or for control with no run; `422` for a bad body.

| Request | Body | Returns |
| --- | --- | --- |
| `GET /api/profiles` | — | The list of profiles, as in `hello` |
| `POST /api/runs` | `profile_id`, `scenario_id`, optional `seed`, `recorded_media` (default false), `zoom_per_station` (0, 1 or 2) | The `run` message |
| `POST /api/run/control` | `action`: `pause` or `play`; or `speed` with `speed`: 1, 2 or 5 | The `run` message |
| `POST /api/alerts/{alert_id}/label` | `label`: `confirm` or `dismiss` | `alert_id`, `seq`, `record_hash` |
| `POST /api/alerts/{alert_id}/export` | — | `alert_id`, `path`, `sha256`, and the hand-off `package` (`docs/handoff.schema.json`, step 6) |
| `GET /api/clips/{station}/{clip}` | — | The recording (H.264 MP4), for a `<video>` element. Seek to `at_s` |
| `GET /api/contract` | — | This contract's JSON Schema |

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
