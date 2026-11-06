# Design — C-UAS Detection Demo

> **How each part thinks** (algorithms) and **how it looks** (dashboard).
> Numbers marked *(start value)* are first guesses to tune during testing, not facts.

---

## Part A — Algorithm design

### A1. Coordinate system

- Local **ENU** frame in metres (x = east, y = north, z = up), origin at the site centre.
- Azimuth `az`: 0° = north, clockwise. Elevation `el`: 0° = horizon, positive up.
- Unit direction of a bearing:

```
d = ( sin(az)·cos(el),  cos(az)·cos(el),  sin(el) )
```

### A2. Simulator

**Scenario file** (`config/scenarios/*.yaml`) lists targets. Each target has a type (`attack_drone`, `quadcopter`, `bird`, `friendly_drone`), start time, waypoints, speed and seed.

**Trajectories:**

- Attack drone: near-straight line at constant speed, about 50 m/s *(start value)*, low altitude (50–150 m).
- Quadcopter: waypoints with hovers, about 5–15 m/s.
- Bird: smooth random wander (curvy heading changes, speed 5–20 m/s), small groups for flocks.

**Station detection model** (per sensor, per frame):

- Max range `R = base_range[sensor][target_type] × visibility_factor` *(start values in `site.yaml`)*.
- Probability of detection at range `r`: `p = p0 × (1 − (r / R)²)` for `r < R`, else 0.
- Bearing noise (standard deviation): RGB 0.05°, thermal 0.1°, acoustic 5° *(start values)*.
- Only targets inside the camera's field of view and above the horizon mask count.

**Hybrid with real AI.** When a simulated target is detected, the station picks a real clip of the same class (drone, bird) from `data/`. The **real video detector** runs on it to produce the "look" confidence and a snapshot. The **real audio classifier** runs on a matching sound clip, mixed with background noise. The noise is louder (lower SNR) with distance and wind. Geometry comes from the simulator, while look and sound come from real models.

**Pickets:** trigger when a target with an engine passes within the hearing radius (attack drone about 1500 m, quadcopter about 300 m *(start values)*, reduced by wind). They report a coarse bearing (±20°), loudness and an engine-type guess, with a 1–2 s delay.

### A3. Station node

1. Receive frames (or the simulated detection event) for each sensor.
2. Video: detector, then ByteTrack, giving boxes with local track IDs.
3. **Track-before-detect (demo version):** a weak detection becomes a bearing only if it is seen in at least **M of N frames** (start: 3 of 5) along a smooth path. This rejects single-frame noise and keeps faint but consistent targets.
4. Convert the box centre to azimuth and elevation using the camera's mounting and lens model.
5. Publish a `BearingDetection` with class probabilities and a snapshot reference.
6. Record clip and audio to `runs/<run_id>/station_<id>/`, with a SHA-256 hash per file.

### A4. Gateway

Rejects a message (and logs a `RejectedMessage`) if:

- the schema is invalid,
- the timestamp is more than 2 s in the future or more than 10 s old *(start values)*,
- the sensor is unknown, or its reported position does not match `site.yaml`.

### A5. Triangulation

Each bearing is a ray from station position `s_i` with direction `d_i`. The best 3D point `p` is the one closest to all rays (least squares):

```
A = Σ w_i (I − d_i d_iᵀ)
b = Σ w_i (I − d_i d_iᵀ) s_i
p = A⁻¹ b          with  w_i = 1 / sigma_i²
```

Accept the point only if:

- the angle between at least two rays is **≥ 15°**, since rays that are nearly parallel give a bad distance, and
- the closest distance between the rays is **< 30 m** *(start value)*.

### A6. Tracking

- **Association:** predict each track forward, then compute the expected bearing from each station. A new bearing matches a track if its angle difference is within 3 sigma. Assign with the Hungarian algorithm (`scipy.optimize.linear_sum_assignment`).
- **New tracks:** unmatched bearings from 2 or more stations whose rays nearly cross create a new triangulated point, which starts a new track.
- **Filter:** constant-velocity Kalman filter on the triangulated position. State is `[x, y, z, vx, vy, vz]`. A bearing-level EKF or IMM is a later upgrade.
- **Status:** `tentative`, then `confirmed` after 3 updates within 2 s, then `lost` after 3 s with no update *(start values)*.
- **Acoustic-only tracks:** a picket or acoustic-only bearing creates a `sector` track (a wedge on the map). It cannot be triangulated well but triggers a pre-alert and cueing.

### A7. Classifier fusion

Three clues per track, each giving P(drone):

| Clue | Source | Notes |
| --- | --- | --- |
| Look `p_look` | Video detector class confidence (average over track) | Zoom crops override wide-camera values when available |
| Move `p_move` | Behaviour rules on track history (≥ 3 s) | See below |
| Sound `p_sound` | Audio classifier | Missing if out of hearing range |

**Behaviour features:**

- mean speed
- speed variation
- straightness (start-to-end distance ÷ path length)
- hover fraction (time with speed < 1 m/s)
- turn rate

Drone-like: high straightness, any hovering, sharp turns. Bird-like: curvy path, steady 5–20 m/s, no hovering *(start rules)*.

**Fusion in log-odds.** Missing clues are skipped:

```
logit(P_drone) = logit(prior) + Σ_m  w_m · ( logit(p_m) − logit(prior) )
prior = 0.1,  w_look = w_move = w_sound = 1.0   (start values)
```

**Attack drone vs quadcopter:**

- attack drone if P_drone is high, speed > 30 m/s and the engine type is piston;
- quadcopter if P_drone is high and the target hovers or is slow.

### A8. Threat ranking

```
P_friendly = 1 if the track matches an approved flight (corridor + time window), else 0   (demo)
P_hostile  = P_drone × (1 − P_friendly)

urgency    = 1.0               if TTI ≤ 30 s
             linear 1.0 → 0.2  for 30 s < TTI ≤ 180 s
             0.1               if TTI > 180 s or no zone ahead

zone_w     = weight of the zone the track is in or heading to
             (critical 1.0, important 0.6, perimeter 0.3)

score      = P_hostile × (0.5 · zone_w + 0.5 · urgency)
level      = red if score ≥ 0.6, amber if 0.3 ≤ score < 0.6, info if lower
```

**TTI (time to impact)** is computed by projecting the track's velocity onto the nearest critical zone. If the closest approach misses the zone, TTI is none.

Every assessment carries **reasons** in plain words, for example `"heading to Processing Unit, 24 s"` or `"fast straight flight + piston engine"`.

### A9. Zoom scheduler

Runs every 0.5 s:

1. Sort tracks by threat score, highest first.
2. For each track, pick the nearest free zoom camera that can see it (in range, in view, visibility OK).
3. Keep a camera on its track for at least 3 s (dwell). Re-task early only if a new track scores at least 0.2 higher.
4. After 1.5 s or more of zoom on a track, use the zoom crop's detector confidence as `p_look`.

### A10. Visibility model

- Each scenario sets a `visibility_factor` between 0 and 1 for cameras (dust, haze) and a `wind_mps` that shortens acoustic range.
- **Coverage %** is the share of site grid cells (25 m cells) seen by at least 2 stations within the reduced range.
- If coverage drops below 80% *(start value)*, the dashboard shows a "coverage reduced" warning.

### A11. Evidence

- Each red or amber alert writes an `EvidenceRecord`: alert ID, track ID, clip paths, metadata JSON, SHA-256 of each file.
- **Hash chain:** each record stores the previous record's hash, so changing any old record breaks the chain. `cuas verify` checks the chain.
- The mock hand-off exports one JSON package per alert: track history, last position, class, score, reasons, clip hashes.

---

## Part B — Dashboard design

### B1. Layout

```
┌───────────────────────────────────────────────────────────────┐
│ Top bar: scenario name · sim clock · ▶ ❚❚ · speed 1x/2x/5x      │
├───────────────────────────────────────┬───────────────────────┤
│                                       │  ALERT QUEUE          │
│            SITE MAP                   │  (ranked, highest     │
│  zones · stations · pickets · tracks  │   first)              │
│  picket sectors · track trails        │  [card] [card] [card] │
│                                       │                       │
├───────────────────────────────────────┼───────────────────────┤
│ Clip panel: zoom clip of selected     │ System status:        │
│ alert + RGB/thermal toggle            │ coverage % · sensors  │
└───────────────────────────────────────┴───────────────────────┘
```

### B2. Map

- Top-down canvas, north up, scale bar.
- **Zones:** filled polygons (critical darker).
- **Stations:** squares. **Pickets:** small dots on the outer ring; a dot flashes when triggered.
- **Tracks:** a dot with a trail (last 20 s) and a velocity arrow. Colour by level: red, amber, grey (info). Every colour also has a text label, so colour is never the only signal.
- **Picket sectors:** a translucent wedge showing the coarse direction of an acoustic-only detection.
- **Toggle:** show bearing rays from stations, useful for explaining triangulation in the demo.

### B3. Alert card

```
● RED   Attack drone 92%           TTI 24 s ⏱
Heading to Processing Unit · 3 stations
Reasons: fast straight flight, piston engine
[Confirm]  [Dismiss]  [Export hand-off]
```

- Countdown updates live.
- **Confirm / Dismiss** are saved as labels for the learning loop.
- Clicking a card selects the track on the map and plays its clip.

### B4. States

| State | What the operator sees |
| --- | --- |
| Pre-alert (picket only) | Amber wedge on map, card "Engine heard, south-east, unconfirmed" |
| Confirmed track | Dot + trail, card with class and score |
| Coverage reduced | Yellow banner "Coverage 64% — dust", greyed map areas |
| Sensor fault | Station square turns grey, status panel lists it |
| No threats | Empty queue with "All clear" and the last-check time |

### B5. Style

- Dark theme (control-room friendly), high contrast.
- One font, two weights. Large numbers for TTI.
- English first. Keep text in a translation file so Arabic (right to left) can be added.

### B6. Demo script (about 7 minutes)

1. **S2 stadium quad (2 min):** show bearing rays crossing, zoom confirmation, alert card.
2. **S3 birds + quad (1.5 min):** birds stay grey, only the drone goes red.
3. **S1 attack wave (2 min):** pickets flash first, pre-alert, three red cards ranked by TTI.
4. **S4 dust (1 min):** coverage banner, reduced map.
5. **Evidence (0.5 min):** export a hand-off JSON and run `cuas verify`.
