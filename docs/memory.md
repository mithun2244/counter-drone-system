# Memory — project state

> The project's notebook. **Read it at the start of every session. Update it at the end.**
> Keep it short: the newest status at the top, old detail trimmed into one-line summaries.

## Current status

- **Current phase:** Phase 5 — Dashboard and evidence, in progress on `phase-5-dashboard`
- **Last session:** 2026-11-09
- **Blocked on:** the user's dashboard (`design.md` B1–B4), on their own branch, being connected to the backend
- **Tested checkpoint:** `91efcd9` on `phase-5-dashboard` (backend, evidence, reference page with basemap and recorded audio; regular suite 980 passed, gate file excluded). The full operator dashboard acceptance stays open
- **Phase 6:** planned and approved (`phases.md`, Phase 6 Plan); not started. Implementation starts only after Phase 5 is accepted and merged, on `phase-6-demo` from `main`. Second-machine (C1) and GPU (C2) checks are pending: no machine named yet
- **Next step:** Phase 5 steps 1–7 are done on `phase-5-dashboard` (backend, evidence and docs; branch published to the private GitHub repo). Step 8: once the user's dashboard is connected, run the Phase 5 acceptance checks on the integrated branch and report them to the user before any merge. The checks are listed in the Phase 5 plan: at least 2 frames a second during S1 in the user's dashboard, `cuas verify` failing on any edit, a valid package per alert, cold start offline, baseline digests and track identity, real time with the dashboard attached, regular suite and fresh clone. Do not rerun the held-out evaluations or the frozen gate
- **Phase 4:** merged into `main` at `8986f71` and published as `main` to the private repo `mithun2244/counter-drone-system`. Post-merge check 14 passed. The frozen gate (`tests/test_decision.py`) ran once, on `ce4ea52` (139 of 139), and is not rerun. Regular suite runs pass `--ignore=tests/test_decision.py`. Gate seed declarations, freezes and both gate runs are under Measured results and in the git history
- **Seeds already seen, so not usable as unseen gate seeds:** development 1–19; 7 (withdrawn from the Phase 4 gates); Phase 3 101–120; Phase 4 gates S1 201–221 and 301–322, S3 201–211 and 301–312, S4 301–312; scenario own seeds 1001, 2002 (S2 and S4) and 3003
- **Start sessions from `cuas-demo/`**, or `CLAUDE.md` will not auto-load

## Decisions log

| Date | Decision | Why |
| --- | --- | --- |
| 2026-11-06 | Sensors: RGB, thermal, zoom PTZ, acoustic arrays, Remote ID, acoustic pickets; no radar or RF | Client constraint; passive-only design |
| 2026-11-06 | Demo = simulator for geometry + real AI on public recordings | No hardware yet; proves the pipeline end to end |
| 2026-11-06 | Single Python process, asyncio, in-process bus behind an interface | Simple for the demo; swappable for a network bus later |
| 2026-11-06 | Messages inspired by SAPIENT (detections and tracks, not raw video) | Matches the real system's ingest gateway |
| 2026-11-06 | Kalman filter on triangulated positions first; bearing EKF/IMM later | Simpler to build and test |
| 2026-11-06 | Detect and report only; no mitigation code | Legal scope in Saudi Arabia; authorities act |
| 2026-11-06 | Git root is `cuas-demo/`; project named `cuas`; `uv_build` backend | `uv` needs a build backend to install `src/cuas`, or `import cuas` fails |
| 2026-11-06 | `.gitignore` uses `data/*` plus `!data/README.md` | `rules.md` §5 keeps data out of git but requires that README; a plain `data/` rule would block it |
| 2026-11-06 | Develop on exactly Python 3.11.16 (`.python-version`); `requires-python >=3.11` | Follows `phases.md` and tests the lowest supported version; numpy 2.5 needs 3.12, so 3.11 locks numpy 2.4.6 |
| 2026-11-06 | S2, a fictional stadium, opens the client walkthrough; geometry, zone IDs and weights are shared, display labels live in scenario metadata | Client walkthrough choice; one site file serves every scenario, with no fallback that could show industrial labels at the stadium |
| 2026-11-06 | Ground truth stays in `cuas.sim`, and only `cuas.metrics` reads it; it never goes on the bus | An evaluator must be able to score the pipeline without the pipeline seeing the answers |
| 2026-11-06 | `zoom_per_station` is 0, 1 or 2, default 1, in `site.yaml` with a `--zoom-per-station` override; unused until Phase 4 | The paired S3 comparison in Phase 4 needs runs that differ only in this value |
| 2026-11-06 | Scenario `seed` drives sensor noise, target `seed` fixes the flight path, one named random stream per sensor and target | Paired runs fly the same routes, and a change to one sensor cannot disturb another's noise |
| 2026-11-06 | S3 and S4 use stadium labels; scenario titles never describe targets | S4 is S2 in dust and S3 follows S2 in the walkthrough; metadata goes to components that must not see truth |
| 2026-11-06 | Stations have 360-degree sensors; friendly drone is modelled but in no scenario | The docs give no camera layout; PRD S1–S4 have no friendly drone, and adding one could break Phase 3's "exactly 3 tracks" |
| 2026-11-06 | Folders only in Phase 0: no `clock.py`, `control/*.py` or `download_data.py` yet | They arrive in their own phases, with tests (`rules.md` §1, §3) |
| 2026-11-06 | Phase 2 detector is SSDLite320 (BSD-3-Clause), not YOLO11n; YOLOX-Nano is the fallback | The vendor says AGPL-3.0 covers fine-tuned models and internal use, and retraining later costs more than choosing now |
| 2026-11-06 | Own ByteTrack-style tracker and numpy mel, not `supervision` or `librosa` | `supervision` 0.31.5 dropped ByteTrack, and current `librosa` needs Python 3.12 |
| 2026-11-06 | Own label reader instead of `mcos-decoder` | The package treats two-box cells as empty frames, which would mislabel the 12 two-drone clips; the install was also blocked by the safety classifier |
| 2026-11-06 | Recordings: Svanström dataset, excluding its 49 YouTube clips and helicopter audio; FSD50K CC0 `Engine` clips as a proxy | Their rights are unverified; the Drone Audio Dataset bars defence and surveillance use (`data/README.md`) |
| 2026-11-06 | Split by scene group: neighbouring clip numbers sharing bin and drone type, joined with clips whose signatures are within 32 of 256 bits | The dataset has no session IDs, and neighbouring numbers alone left 15 of 38 RGB test clips with a near-identical training clip. Still a stand-in that cannot prove two groups are separate flights |
| 2026-11-06 | Clips are matched to simulated range; M-of-N does not drop bearings | Mixing all bins would overstate results; keeping geometry leaves Phase 1 bearings identical |
| 2026-11-06 | FSD50K clips read by HTTP range requests with our own zip directory reader | Stores only the selected clips instead of downloading 6.2 GB; `zipfile` refuses a multi-part zip64 archive |
| 2026-11-07 | Look period 0.6 s; the media link refuses a period that is not whole ticks | `round(0.5 / 0.2)` silently gave 0.4 s |
| 2026-11-07 | Movement clue (`design.md` A7): drone-like if hover fraction ≥ 0.2, with hover from 2 s of position change, or if fast, straight and steady flight lasts 5 s of fresh fixes. A7's sharp turns and straightness alone are dropped. Coasting never counts, and never raises an alert | Measured on Phase 3 tracks, seeds 1–19 except 7: A7 as written turned 208 of 313 S3 bird tracks red, because birds turn constantly and fly straight for 10 s at a time. Approved by the user with these conditions |
| 2026-11-08 | Phase 5 map: a local vector map of the fictional site from `site.yaml`, in local metres, with no tiles or upload. The operator picks a saved site profile and starts monitoring. Production direction: MapLibre GL JS with self-hosted PMTiles and a surveyed, client-approved map (`docs/mapping.md`) | User decision. The site is fictional, the demo must work offline from a cold start, and tracking, alerts and evidence must not depend on the map background |
| 2026-11-08 | Phase 5 dependencies: `fastapi` (MIT), `uvicorn` (BSD-3-Clause) and `websockets` (BSD-3-Clause, Uvicorn's WebSocket support); `httpx` (BSD-3-Clause) for tests only. They bring `starlette`, `anyio`, `annotated-doc`, `h11`, `click`, `idna` and `opentelemetry-api` (Apache-2.0, an API only: nothing is recorded or sent without an SDK); `httpcore` and `certifi` (MPL-2.0) for tests only. Evidence: a JSONL hash chain and a dedicated evidence bus | Approved by the user. FastAPI with a WebSocket is the architecture's dashboard choice. Starlette 1.10 warns that `httpx` is deprecated for its test client in favour of `httpx2`; kept, as the user chose |
| 2026-11-09 | Phase 5 evidence: one JSON Lines chain per run folder (`evidence/chain.jsonl`), records `alert`, `escalation` (first time red only), `label` and `export` (on request and for every alert at run end). The dashboard sends `OperatorLabel` and `ExportRequest` on a fourth, evidence bus and waits for the record with its request ID. `cuas verify` lives in `src/cuas/cli.py` | Approved plan (JSONL chain and evidence bus approved by the user). `cli.py` sits outside the components because `evidence` may not import the station's `verify_recordings` |
| 2026-11-09 | Operator display basemap: OpenStreetMap vectors of Portsmouth, UK, under the unchanged fictional site, always labelled "Simulated scenario". The anchor is 50.78497, -1.09457: Southsea Common's OSM centroid moved 80 m north so all stations sit on land. The script projects the map into site metres once, so frontends use one ENU-to-screen transform. No basemap gives a 404 and a local grid. Served at `GET /api/basemap`, its own schema, contract kept at version 1 | User decisions (basemap, OSM vectors on canvas, Southsea Common, anchor after the fetch report). Reverses the first Phase 5 "no map background" choice for the display only; tracking, alerts and evidence never use the map. No new dependency: standard library fetch, canvas drawing |
| 2026-11-09 | Recorded audio: `TrackClass.looks` also keeps each station microphone's latest sound window (`stN.acoustic`). Alert cards gain `sounds` (station, WAV URL), kept apart from `looks` so `looks` stays video; `/api/clips` also serves the run's WAVs. Alert snapshots and hand-off packages list the WAVs heard so far, with their hashes (S2: none at the t=15.8 alert, all three stations in the end-of-run package). The reference page plays them under "Recorded audio", labelled clean source audio. Contract kept at version 1: an added field defaulting to `[]` | User request; approved plan. The classifier heard each window mixed with noise, so the page must not present the clean file as what it heard. Recorded-media control digests change (new `looks` entries); simulator-only runs and every sensor digest are unchanged; committed samples differ only by `"sounds":[]` |
| 2026-11-09 | Phase 6 plan approved: metrics report per run, `--demo <scenario>` and `--demo full` from `config/demo.yaml`, a presenter-advanced playlist (`POST /api/playlist/next` and a `playlist` field on `RunInfo`, contract kept at version 1), `check_setup.py`, a CRLF `.gitattributes` rule for the media manifest, a root README. Tasks are split into independent of the dashboard (A), needing the full operator dashboard (B) and needing user hardware (C) | User decisions: plan only and wait for Phase 5 to be accepted and merged (`rules.md` §1); the presenter advances the playlist; the second machine is not known yet |
| 2026-11-09 | Hand-off package gains `highest_level` beside `level` | Exports at run end showed S1's attack drones as `info` once their flight ended; the package must show the alert reached red |
| 2026-11-09 | `verify_recordings` also fails on a `hashes.json` not byte for byte as the recorder wrote it, or unreadable | Appending a newline to it went undetected, and a broken one crashed the check |
| 2026-11-09 | Live runs: frames also come on the clock, one tick behind it, and the latest frame is sent again when an evidence record is written | Without the first, S1 at 1× gave 1 frame a second, below FR-11's 2. Without the second, a label given while paused did not reach the card until play. Neither changes the contract schema |
| 2026-11-09 | `run_demo.py --dashboard` starts live runs, each in a fresh `runs/<scenario>_seed<seed>_<NNN>/`; `--evidence` keeps evidence for a plain `--scenario` run | Approved plan, step 5. No run overwrites or mixes with another |
| 2026-11-08 | Phase 5 split: the user builds the full B1–B4 dashboard on their own branch. Claude Code builds the backend, the evidence tools and a minimal reference page, with the WebSocket contract and a sample stream first. Acceptance runs once the user's dashboard is connected | User decision |
| 2026-11-08 | Zoom (`design.md` A9) gives class evidence only, and only with recorded media. A task takes effect one 0.6 s period after it is issued, so the scheduler aims 1.5 periods ahead. A target within 1° gets a real RGB look on a held-out clip chosen as if 4× closer, avoiding the clips wide cameras use for it. A zoom look on a frame the track already used as a wide look is not counted. Zoom bearings never open or close a batch. The demo default stays one zoom camera per station | Approved by the user. Paired S3 comparison (5 seeds): zoom reduced false alerts overall (37, then 24 with one camera, 21 with two), did not speed up the quadcopter's red alert, and did not change tracks |
| 2026-11-08 | Mast bias is reported by `scripts/mast_bias.py` through a `MastBias` wrapper on the sensor bus, not under a pytest marker as the plan said | It is a report with no pass or fail, like the zoom comparison. The wrapper leaves the simulator and pipeline unchanged |
| 2026-11-08 | Time to impact comes from a least-squares fit to real fixes over the last 5 s, published once they span 3 s. After a gap the fit reaches back to the newest real fix at least 3 s old, never older than 6.5 s. Coasting predictions never enter it | With 2 s, a new track's early estimate jumped the queue (S1 seed 216, first gate run). With 3 s and no reach-back, a 2.2 s gap in S4 seed 10 dropped a red alert to info for one batch. A live track can need a 6.0 s fix: up to 2.8 s in the window plus a gap of up to 3.2 s, because the tracker applies fixes before its loss check. Development seeds: 36 of 54 S1 drones reach red 0.6 to 1.2 s later, and nothing else changed. Approved by the user |
| 2026-11-07 | Phase 4 runs with no class data gate S1 and S3; recorded media and mast bias are reported separately. `alert_id` is kept apart from `track_id`; zoom supports classification but never position | Approved by the user on 2026-11-07, decisions 1 to 9 of the Phase 4 plan |
| 2026-11-07 | Shared tracker: a 2-station fix that other bearings could have paired with differently neither starts a track nor counts towards confirming one. Confirmation needs corroborated fixes: 3 stations, or nothing else unexplained (`design.md` A6) | Rays from different drones cross where nothing is. `design.md` as written confirmed such ghosts, and a throwaway prototype gave exactly 3 S1 tracks on only 2 of 10 seeds. With this rule the real code gives 3 on all 22 seeds tested |
| 2026-11-07 | The bearing gate includes the track's own uncertainty; rays must also meet within 4 bearing sigmas; a fix within 30 m of a live track updates it | Prototype, S1 over 20 seeds: removing each of these gave exactly 3 tracks on 9, 19 and 0 seeds |
| 2026-11-07 | `SectorTrack` is its own message, with no position, range or elevation field. Acoustic bearings never place a target in 3D | It cannot carry a 3D claim by construction, and it closes the old issue that `Track.status` had no `sector` value |
| 2026-11-07 | Three in-process buses: sensor, ingest and control (`architecture.md` section 5) | The approved plan said two. With two, the tracker read the control bus and published to it, so closing it would drop the last batch. Each stage now reads one bus and writes the next. Approved by the user on 2026-11-07 |
| 2026-11-07 | Dropped the `design.md` A4 check of a sensor's reported position | No message carries one. The tracker uses only `site.yaml` positions, so a false one cannot affect it, and adding the field would change every Phase 1 digest |
| 2026-11-07 | Coasting tracks keep publishing a predicted position for up to 3 s, with `n_stations = 0` | Dropping them would break tracks at every brief gap. Phase 4 must not alert on `n_stations = 0` alone |
| 2026-11-07 | No `filterpy`: our own constant-velocity filter in numpy. No new dependency in Phase 3 | About 25 lines, and `filterpy` was never installed |
| 2026-11-07 | The user accepted the documented limits for the Phase 2 demo: false drone tracks, the Distant validation and test gap, unmeasured empty-sky false alarms, narrow S2 look evidence and the rest of Known issues | Phase 2 has no accuracy target, and results are reported as measured. This covers the Phase 2 demo only, and the limits stay listed because they are still true |
| 2026-11-07 | The user approved an exception for the decode, tracker and audio timing shortfalls; exactly what was missed is under Exceptions to the Phase 2 plan | These stages are small next to camera inference: tracker 0.1 ms and decode 4 ms against 90 ms, and audio 4.1 ms per 1 s window |
| 2026-11-07 | Thermal detector trained on a Colab T4 (20 epochs, 7.3 min in the training loop, 0.086 s per batch) and evaluated once on this laptop's CPU; RGB and audio stay CPU-trained | The local CPU run was killed at epoch 16 and Colab's CPU was too slow. Evaluating here keeps CPU timings on the machine the plan measures |
| 2026-11-07 | Opt-in `--device cuda` for detector training, with the CUDA build of torch installed on Colab only (`docs/colab_gpu.md`); CPU stays the default and `uv.lock` is unchanged | The user measured Colab's CPU at 3.5 s per batch, and 20 epochs inside the 120-minute budget need 1.4 s or less. The model returns to the CPU for saving and validation, so the weights and threshold suit the CPU evaluator |
| 2026-11-07 | Detector training saves a checkpoint each epoch and resumes from it | A low-memory kill cost 82 minutes because weights were saved only at the end |
| 2026-11-06 | Use Superpowers (official marketplace version) for focused debugging, testing and code review when useful; skip its brainstorming and writing-plans; ask before separate worktrees or subagents (rules in `CLAUDE.md`) | `docs/phases.md`, `docs/rules.md` and approval in Plan Mode stay the one project workflow |

## Mocks and stubs in use

- Station geometry, bearings and acoustic direction: simulated
- Pickets: simulated
- Zoom camera: simulated pointing and field of view; with `--recorded-media`, a real RGB look on a held-out clip chosen as if the target were 4× closer, not a crop of the wide camera's frame. Without recorded media it sees nothing
- Hand-off: JSON export only, marked `"mock": true`; nothing is sent
- `docs/samples/edge_states.jsonl`: hand-made dashboard states the simulator never produces, marked MOCK
- Bearing `class_probs` and `snapshot_ref`: real with `--recorded-media`; empty without it, and on S1 camera bearings because no fixed-wing footage exists
- Picket engine guess: real classifier with `--recorded-media`, otherwise a noisy simulated value
- Picket loudness: always simulated (`sim/picket.py`)
- Sensor health: simulated sensors never report a fault
- National air picture: not in the demo

## Known issues and risks

- Before client delivery: counsel review of weights and recording rights; the to-do list is in `data/README.md`
- All speeds, ranges and thresholds are start values to tune; so are the `site.yaml` mast heights, zone sizes, `p0` values, base ranges, tick and picket settings, which the docs do not specify
- Determinism is proven for the same lockfile on the same machine, not byte for byte across machines; Phase 6's second-machine check should compare behaviour
- `nvidia-smi` is not available on the dev machine, so it probably has no NVIDIA GPU; this affects Phase 2 training and the open GPU question
- SSDLite's coarse features may miss small targets; 85% of thermal drone clips show targets 15 px wide or smaller
- False drone tracks survive M-of-N on both cameras: thermal 6 of 31 non-drone test clips (0.092 to 0.363), RGB 7 of 19 (0.191 to 0.590). The intervals overlap, so neither camera is shown to be better. They treat clips as independent, but thermal's 31 come from 13 scene groups, so the true range is wider. Thermal's report does not say which clips or classes produced the 6, and naming them would take another test run. Phase 3 should not treat one camera's confirmed track as proof of a drone
- Test results rest on few scenes, so their intervals are too narrow: RGB's 17 drone clips come from 3 scene groups, thermal's 24 from 6
- The Distant drone miss rate is not comparable between validation and test, and neither figure measures small targets in general. Thermal: 0.757 on validation (7 clips, 2 scene groups, 6 clips of Phantom 4 Pro, median box 9.7 px wide) against 0.072 on test (7 clips, 2 scene groups, all F450, 16.5 px). RGB: 0.817 (6 clips, 1 scene group, Phantom 4 Pro, 19.9 px) against 0.085 (4 clips, 1 scene group, F450, 27.4 px). Thermal's test Distant boxes are as wide as its validation Medium boxes (17.0 px, miss rate 0.05), and 46 of the 53 validation misses come from 5 clips of one scene (`IR_DRONE_151`). So the test figure reflects a larger drone and the validation figure mostly one scene. Clip counts, drone types and box sizes were counted from the manifest and labels with a one-off script, not the metrics script
- False alarms on empty sky are unmeasured: 0 of thermal's 3,459 scored test frames lack a target, and 1 of RGB's 2,264 (counted from labels), so the report's `Any box on a frame with no target: 0` tests nothing
- Thermal separates other aircraft poorly at frame level: airplane precision 0.307, recall 0.205; helicopter 0.284, 0.198; 391.7 false detections per 1,000 frames across all classes
- S2's look evidence is narrow. Each sensor draws on one scene: RGB 2 clips of `V_DRONE_026`, thermal 3 of `IR_DRONE_096`, acoustic 2 of `audio_DRONE_006`, and both cameras use only F450 Distant clips while simulated range is 209 to 766 m. The Distant bin starts at 60 m and the dataset gives no exact distances, so S2's share of non-zero drone confidence is not a detection rate at those ranges
- No test checks the real trained weights' S2 confidences. `test_s2_bearings_carry_real_output_and_the_same_geometry` only needs them non-empty. Two tests in `tests/sim/test_media.py` now catch forced-zero confidences and an RGB model on the thermal path (9 of 9 sabotages), with real loading and inference, but on checkpoints built to give a known answer. So damaged weights that only output zeros would pass; the real share is reported, with no target, as the plan says
- The audio classifier does not beat its baseline: 0.750 clean against 0.773 for always answering `engine`, which is 34 of 44 test clips. Nine engine clips are called background
- **Follow-up check, kept open by the user on 2026-11-07:** concurrent live-stream performance is unproven. S2 with all three models keeps real time (125 s wall clock, check 18) only through a per-frame memo, with each sensor using 2 or 3 clips. By calculation, 6 unmemoised streams at one look per 0.6 s need about 864 ms of CPU per simulated second (RGB 82.5 ms and thermal 90.3 ms at 4 threads). Measure six separate streams before relying on live video
- The CUDA path has run for real: the user's T4 completed 20 epochs, and its weights load and evaluate on this CPU. Whether that run resumed is not recorded, so resuming on a GPU stays unproven. No CPU run of thermal exists to compare with
- The manifest hash depends on line endings: `bc49b46d` on Windows with `autocrlf`, `ba662739` for the committed bytes. A fresh Linux clone would have its weights refused by `evaluate_media.py`, so Colab must use a ZIP built with `git archive` on the Windows machine. Worth fixing before Phase 6's second-machine check
- This laptop has 7.7 GB of RAM, and long training competes with everything else open. The training time budget is wall clock, so it also counts sleep
- S4's dust reduces simulated range but is not applied to the frames
- The simulator's 800 m RGB range for a quadcopter is a start value this footage cannot support: the dataset's Distant bin starts at 60 m
- The engine class is mostly road vehicles: a proxy, not evidence of detecting a one-way attack drone
- The dataset has no fixed-wing drone, so S1 camera bearings have no real look evidence
- **Follow-up, kept open by the user on 2026-11-07:** **bird tracks fragment in S3, and Phase 4 depends on them.** Over 7 seeds: 19 to 30 confirmed tracks for 13 targets, 29 false tracks in total and 14 overlapping duplicates, all among the birds. The quadcopter kept one track on every seed. Phase 4's "birds never reach amber or red" must cope with ghost and fragment tracks; swarm tracking stays in Later
- **Follow-up, kept open by the user on 2026-11-07:** **mast bias.** Tracking is shown only for the simulator, which has no sensor bias, clutter or timing error. In the throwaway prototype, a fixed 0.2° azimuth bias on one station dropped S1 to 19 of 20 seeds, and 0.5° to 9 of 20 (worst median 14 m). A real site needs mast calibration first
- In S1, 3D tracks begin 1.6 to 1.8 km from the site centre, because of the 15° rule with 500 m baselines, though cameras see 3 km. In between there are only picket wedges
- **Follow-up, kept open by the user on 2026-11-07:** **coasting without fresh observations.** A track coasts for up to 3 s after its last fix, marked `n_stations = 0`: up to 150 m of extrapolation once an attack drone's flight has ended
- S1 starts 3 to 6 tracks per seed for 3 confirmed. A tentative track left at rest falls behind, and the next fix lands more than 30 m away. These are never confirmed, but they are published as tentative
- **Follow-up, kept open by the user on 2026-11-07:** **re-acquisition under a new ID.** S2 picks its target up again under a new ID on 2 of 22 seeds, and S4 on 1 of 7, after coverage gaps at the edge of range. They never overlap
- Station acoustic wedges also appear near tracked targets: 3 in S1 seed 7. A likely cause, not checked case by case: a 3-sigma gate in two dimensions leaves about 1% of bearings outside
- The test suite now takes about 5 to 8 minutes here (717 tests), mostly from the 44 seeded S1 and S2 acceptance runs and the real-media tests
- **`prd.md` time to alert (≤ 5 s from the first 2-station detection to red) is missed** and stays marked missed. Baseline, development seeds: all 108 drones over 5 s, worst 65.0 s; in S1 the 15° rule delays the first 3D fix by a median 20.7 s. Recorded-media S3: the quadcopter takes 19.2 to 30.6 s on 5 seeds, the same at 0, 1 and 2 zoom cameras
- **Recorded-media S3 alerts on birds.** With real models, birds and false tracks raise 4 to 10 alerts per run with no zoom (5 seeds), because the detectors give some bird clips drone looks (Phase 2's false drone tracks). Zoom lowers this but never removes it. Baseline S3, which has no class data, raises none
- **Real time for recorded-media S3, fixed on 2026-11-08:** it was 100, 101 and 102 s at 0, 1 and 2 zoom cameras, against 97.2 s allowed. Profiling showed tick 0 costs about 2.6 s (model inference 2.2 s on the first frame of every stream, clip decoding 0.4 s). Pacing started only after tick 0, so that time was never caught up. `SimClock.start()` now starts pacing when the run starts. That is a pacing fix, not a speedup. Now 94.6, 94.5 and 94.5 s, with every output byte-identical to before. The run is up to 4.6 s behind real time in its first seconds and on time from 30 s. Startup before the run is 3.6 s. Baseline S1 (121 s) and S3 (91 s) keep real time
- **Mast bias** (`runs/robustness/mast_bias.md`; reported only): with st1 off by 0.2°, S1 has exactly 3 tracks on 17 of 18 development seeds and the worst target median is 9.0 m; at 0.5°, 9 of 18, 6 false tracks, worst target median 25.7 m and red order wrong on 6 seeds. S3 birds never reached amber or red at either bias. A real site needs mast calibration first
- **Evidence: the newest records.** Removing the newest record together with the file it lists leaves a valid, shorter chain, and `cuas verify` passes (pinned by a test, `design.md` A11). Exports carry the chain head and the dashboard shows it; a real system needs an outside anchor
- Evidence: a recording no alert's looks or sounds use (for example the background-noise WAV mixed into each sound window) is protected only by the recorder's hash list, which no record anchors. Labels and exports need a live run (`409` otherwise)
- The export response rounds the package's numbers to 3 decimals like every number sent; `sha256` is of the stored file, which keeps full precision
- Starting a recorded-media dashboard run loads the models in the server's event loop, so the server stalls for a few seconds (marked `ponytail:` in `scripts/live_runs.py`)
- The committed sample streams carry no evidence (`evidence_head` null)
- Basemap: `data/basemap/` is not committed, so a fresh clone draws the local grid until `scripts/fetch_basemap.py` runs (one Overpass request; on 2026-11-09 the main instance answered 502, a mirror timed out, and a later retry worked; `--endpoint` picks another instance). Pickets pk4–pk7 lie in the water at this anchor. The basemap is OSM under ODbL: the attribution must stay visible
- Phase 4: `design.md` A10 does not say which range or grid coverage uses, and S4's result depends on it. Paper calculation at S4's visibility 0.5: `important` zone with quadcopter RGB range gives 100% clear and 55% in dust (works); perimeter with attack drone RGB stays at 100% (warning never fires); perimeter with quadcopter RGB is 45% even in clear air (warning always on)

## Exceptions to the Phase 2 plan

Approved by the user on 2026-11-07, for the Phase 2 demo. The plan's CPU time requirement: mean, p50 and p95 over at least 1,000 frames, split into decode, inference and tracker, at 1 and 4 threads, with CPU, thread count and torch version; audio the same, per window. The test reports stay as they are, and no validation-only timing run was done.

| Requirement missed | Thermal | RGB | Audio |
| --- | --- | --- | --- |
| Tracker and M-of-N over at least 1,000 frames | 976 looks | 642 looks | Not applicable |
| Decode p50 and p95 over at least 1,000 frames | One value per clip: 55, covering 4,215 kept frames | One value per clip: 36, covering 2,762 kept frames | Not timed: WAV reading is outside the row |
| Timing at both 1 and 4 threads | Met | Met | One setting only |
| Thread count stated | Met | Met | Not stated: `evaluate_sound` sets none, so it ran on torch's default |

- **Decode values:** each is a clip's whole decode time divided by its kept frames, so it includes frames decoded and skipped, and the report's mean is a mean of clip averages
- **Met:** inference at 4 threads (4,215 and 2,762 frames) and at 1 thread (1,000 each), the audio classifier count (3,130 windows), CPU and torch version in every report
- **To close these later:** validation alone needs new timing code, because one pass gives 964 and 584 looks, decode needs per-frame timing and audio needs a thread setting. `evaluate_media.py --split val` is the wrong tool, because it appends to `attempts.jsonl` and labels its report HELD-OUT

## Measured results

### Recorded media, held-out split (`scripts/evaluate_media.py`, `runs/eval/`)

- **RGB detector** (weights `7aa15d48`, threshold 0.15 from validation, second evaluation of these weights on test): drone clips confirmed 17 of 17 (95% interval 0.816 to 1.000); other clips with a false drone track 7 of 19 (0.191 to 0.590); median 1.2 s to confirm. Drone frames: precision 0.805, recall 0.837, and 0.673, 0.700 at IoU 0.5. Drone miss rate: close 0.283, medium 0.159, distant 0.085. Inference mean 82.5 ms at 4 threads, 102.4 ms at 1
- **Audio classifier** (weights `2457d275`, first evaluation on test, 44 clips; the engine class is a proxy): accuracy 0.750 clean (0.606 to 0.854), then 0.750, 0.636, 0.523, 0.273 at +20, +10, 0, -10 dB. Misses 9, 9, 13, 18, 31; false detections 0 throughout. 4.1 ms per 1 s window
- **Thermal detector** (weights `0fc7c5a1`, trained on a Tesla T4, threshold 0.2 from validation, first evaluation on test, run on this laptop's CPU): drone clips confirmed 24 of 24 (95% interval 0.862 to 1.000); other clips with a false drone track 6 of 31 (0.092 to 0.363); median 1.2 s to confirm. Drone frames: precision 0.792, recall 0.897, and 0.721, 0.817 at IoU 0.5. Drone miss rate: close 0.189, medium 0.065, distant 0.072 (validation: 0.275, 0.05, 0.757). False detections 1,355 in 3,459 frames, including 85 drone boxes on bird, airplane or helicopter clips. Inference mean 90.3 ms at 4 threads, 104.4 ms at 1

### Hybrid S2 run (simulated geometry, real model output on held-out clips; not a detection rate)

- Seed 7, all three models: digest `sha256:134cb33f6b12005771cf400130813388c678112cc3ed483c90833f0cda5299c0`. Two fast runs and one real-time run are byte-identical
- Counted from the saved output with a one-off script, not the metrics script: bearings with non-zero drone confidence, RGB 1,121 of 1,127 and thermal 736 of 820. Acoustic top class on 80 bearings: `electric_drone` 64, `background` 12, `engine` 4

### Phase 4 (simulator results, not real-world performance)

- **Gates, baseline simulator:** first run on `2ded003` 67 of 68 (S1 seed 216 order); second run on `ce4ea52` 139 of 139, on S1 301–322, S3 301–312 and S4 301–312 never run before
- **Development seeds** (1–19 except 7), frozen rule: 0 bird or ghost alerts, every drone one alert, S1 red order wrong in 0 of 2,926 batches, no red alert without a time to impact. 36 of 54 S1 drones reach red 0.6–1.2 s later than with the 2 s minimum
- **Coverage:** S4 54.8% with the warning set; S2 100%
- **Digests, seed 7:** S1 `ca3cfe6d`, S2 `aacb735a`, recorded-media S2 at zoom 0 `134cb33f`, all unchanged. Recorded-media S3 with two zoom cameras is byte-identical across two processes

### Paired S3 zoom comparison (`scripts/compare_zoom.py`, commit `98b14e1`; simulator geometry with real model output on held-out clips; reported only)

- Seeds 3003 and 1–4, each at 0, 1 and 2 zoom cameras per station, same scenario inputs and recordings. Tracks byte-identical across the three on every seed
- False alerts (alert IDs on birds or false tracks), summed over 5 seeds: 37 with no zoom, 24 with 1, 21 with 2. False amber or red assessments: 1,050, 447, 487. Per seed not consistent: seed 4 got worse with 1 camera (4 to 5 alerts, 123 to 163 assessments), and a second camera was better than one on 2 seeds and worse on 2
- The quadcopter reached red in all 15 runs, at the same time with 0, 1 or 2 cameras on every seed: time to red from the `prd.md` start event 19.2, 30.6, 25.6, 24.4 and 21.8 s. No improvement from zoom
- Zoom bearings sharing a frame with a wide look of the same target, which the classifier does not count: 114 to 397 of 990 to 1,326 with 1 camera, 206 to 972 of 2,255 to 2,689 with 2. Few held-out clips stand in: RGB drone distant 4, bird distant 2, bird medium 6

### Simulator (`cuas.metrics.evaluator`; simulator results, not real-world performance)

- S2 seed 7: 2,027 bearings from 3 stations, quad-1 seen st1=853, st2=658, st3=516. Geometry is identical with and without recorded media
- **Tracking, S1** (`cuas.metrics.track_evaluator`, 22 seeds: its own, 7 and 101 to 120, which the design prototype never ran): exactly 3 confirmed tracks on all 22, no false tracks and no duplicates. Median error 0.89 to 1.08 m, worst p95 7.13 m, worst target median 1.38 m. First confirmation 1,620 to 1,820 m from the site centre. No messages rejected
- **Tracking, S2** (same 22 seeds): one confirmed track on 20 seeds, a sequential re-acquisition on 2. Median error 0.33 to 0.37 m, worst p95 1.61 m
- **Tracking, S3 and S4** (7 seeds each, reported only): S3 as under Known issues, median 0.60 to 0.67 m but worst p95 142 m; S4 one track on 6 of 7 seeds, median 0.61 to 0.70 m
- With the tracker: S1 ran in 121 s, S3 in 91 s and S2 with recorded media in 126 s, each byte-identical to its fast run. Recorded media leaves tracks byte-identical

## Open questions (copy of `prd.md` §10, tick when answered)

- [x] First site type for the demo: oil and gas or stadium? **Stadium: S2, a fictional stadium, opens the walkthrough (2026-11-06)**
- [ ] Dashboard language: English, Arabic or both?
- [x] Acceptable detector licence for the client demo? **For now, permissive only: BSD-3-Clause SSDLite; counsel to review the weights before delivery (2026-11-06)**
- [ ] GPU laptop available for the live demo?

## Session log (newest first)

### 2026-11-09 — GitHub handoff (docs only)
- Done: confirmed `663f010` was on GitHub. Added a repository entry point in `README.md`, added `GITHUB.md`, and refreshed the commands and workflow in `CLAUDE.md`.
- Decision: review and update affected documentation before publishing changes to GitHub (`rules.md` §8).
- Next step: Phase 5 acceptance with the full operator dashboard. See Current status.

### 2026-11-09 — Phase 6 plan (docs only)
- Done: Phase 6 plan written into `phases.md` and approved; `91efcd9` recorded as the tested Phase 5 checkpoint. No Phase 6 code.
- Decisions: see the log above.
- Next step: see Current status. Phase 5 acceptance with the full operator dashboard comes first.

### 2026-11-09 — Phase 5, recorded audio on the reference page
- Done: microphone recordings carried from the station bearing to the alert card, served as WAV, listed in evidence, and played under the Clip video on `/reference/`, labelled clean source audio.
- Decisions: see the log above.
- Next step: see Current status.

### 2026-11-09 — Phase 5, Portsmouth basemap
- Done: `cuas.dashboard.basemap` (model, projection, loading), `scripts/fetch_basemap.py` (fetch, projection, simplification, sea assembly from the coastline, report), `GET /api/basemap`, reference page basemap, notice, attribution and grid fallback, docs. The user builds the operator dashboard; the contract doc gives them the transform, draw order, pause and export notes.
- Decisions: see the log above.
- Next step: see Current status.

### 2026-11-08 to 11-09 — Phase 5, steps 1–7
- Done: mapping decisions (`docs/mapping.md`); dashboard contract v1 with schema, samples and frame builder; clock pause, resume and speed; FastAPI server with WebSocket, replay and reference page; live runs from the composition root; evidence store, keeper, labels, exports, hand-off package and `cuas verify`; docs. Regular suite 955 passed before step 7 (gate file excluded). Step 5: 7 of 7 sabotages caught after one invalid one was replaced. Step 6: 15 of 15, after one added test. Dashboard runs, with pause, labels and exports, give control digests identical to plain fast runs. Baseline sensor digests unchanged.
- Decisions: see the log above.
- Issues / mocks: see the lists above.
- Next step: see Current status.

### 2026-11-07 to 11-08 — Phase 4
- Done: movement clue, fusion, threat ranking, alert identity, coverage, zoom scheduler, zoom looks from recorded media, alert evaluator, gate tests, paired zoom comparison, mast-bias report, `design.md` A7 to A10. The rule was frozen before each gate run. The first gate run failed on S1 seed 216 and was kept on record; the second passed 139 of 139. 10 of 10 zoom sabotages and 4 of 4 time-to-impact sabotages were caught.
- Decisions: see the log above. Seed 7 was withdrawn from the gates after a smoke test saw it. A Phase 1 `run_demo` test now expects the header to say zoom looks need recorded media, not that zoom is unused.
- Issues / mocks: see the lists above. Real time is missed for recorded-media S3, and the `prd.md` 5 s time to alert is missed.
- Next step: see Current status.

### 2026-11-07 — Phase 3
- Done: gateway, triangulation, filter, association, shared tracker, sector tracks, pipeline wiring and track evaluator. A throwaway in-memory prototype tested the design before any code. 717 tests pass, and a fresh clone with no data or models gives 696 passed, 21 skipped. 18 of 18 sabotage checks caught, one after a stronger test was added. Every acceptance check that can run before the merge passes. The user approved the merge, including the three-bus design; this was committed before the merge, so check 19's result is in the report to the user.
- Decisions: see the log above.
- Issues / mocks: see the lists above. No new mocks: sensor positions come from `site.yaml`.
- Next step: see Current status.

### 2026-11-06 to 11-07 — Phase 2
- Done: RGB and thermal detectors, tracker, M-of-N, audio classifier, SNR mixing, hybrid link, recorder, opt-in CUDA training and all three test reports. Every check that can run before merging passes. On the last code commit, `36bad0a`, 546 tests pass with none skipped, and a fresh clone with no data or models gives 526 passed, 20 skipped. Check 23 runs on `main` right after this commit merges, so its result is in the report to the user, not here. All planned sabotage checks were caught; 2 extra probes of the all-model S2 test were not, which led to two new tests that catch 9 of 9.
- Decisions: see the log above. Stricter scene-based splits replaced neighbouring clip numbers after a leak check. The user accepted the documented limits and approved a timing exception.
- Issues / mocks: see the lists above. Thermal training was killed by the low-memory reaper at epoch 16 and kept nothing, which led to per-epoch checkpoints and then training on a T4.
- Next step: see Current status.

### 2026-11-06 — Between Phase 1 and Phase 2
- Done: added user-level tools outside this repo (`karpathy-guidelines` skill, Superpowers plugin) and set the rules for using them in `CLAUDE.md`.
- Decisions: see the log above.
- Issues / mocks added: none.
- Next step: once this docs branch is reviewed and merged, plan Phase 2.

### 2026-11-06 — Phase 1
- Done: typed messages, in-process bus, simulated clock, typed site config, four fictional scenarios, trajectories, station and picket models, engine, evaluator and `run_demo.py --scenario`. All `phases.md` checks pass, 307 tests, and 8 of 8 sabotage checks were caught.
- Decisions: see the log above. S2 opens the walkthrough. Ground truth reaches only the evaluator. `zoom_per_station` is carried for Phase 4.
- Issues / mocks added: see the lists above. No new dependencies.
- Next step: plan Phase 2 on a new branch, without starting code until approved.

### 2026-11-06 — Phase 0
- Done: installed `uv` with winget, created the git repo, folder layout, `pyproject.toml`, `uv.lock`, `site.yaml`, `run_demo.py` and the smoke test. All `phases.md` checks pass.
- Decisions: see the log above. Also set pytest-asyncio's fixture loop scope to `function` to stop a deprecation warning on every test run.
- Issues / mocks added: no new mocks. Open questions remain unanswered.
- Next step: plan Phase 1 on a new branch, without starting code until approved.

<!-- Template:
### YYYY-MM-DD — Phase N
- Done:
- Decisions:
- Issues / mocks added:
- Next step:
-->
