# Memory — project state

> The project's notebook. **Read it at the start of every session. Update it at the end.**
> Keep it short: the newest status at the top, old detail trimmed into one-line summaries.

## Current status

- **Current phase:** Phase 2 — Station AI, on `phase-2-station-ai`, not merged. All three models are trained and have test reports
- **Last session:** 2026-11-07
- **Blocked on:** the user's review: whether to accept the limits under Known issues, and whether the timing shortfall needs a validation-only run
- **Next step:** once cleared, tick `phases.md`, merge into `main` with `--no-ff` (do not push), then run check 23: clean tree, and checks 3, 5, 7, 8 again on `main`. Every other acceptance check passes on `ff71287`, and the full suite and fresh clone pass again on `36bad0a`, which only adds tests. Do not rerun the held-out evaluation. Phase 3 needs its own plan and approval
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
| 2026-11-07 | Thermal detector trained on a Colab T4 (20 epochs, 7.3 min in the training loop, 0.086 s per batch) and evaluated once on this laptop's CPU; RGB and audio stay CPU-trained | The local CPU run was killed at epoch 16 and Colab's CPU was too slow. Evaluating here keeps CPU timings on the machine the plan measures |
| 2026-11-07 | Opt-in `--device cuda` for detector training, with the CUDA build of torch installed on Colab only (`docs/colab_gpu.md`); CPU stays the default and `uv.lock` is unchanged | The user measured Colab's CPU at 3.5 s per batch, and 20 epochs inside the 120-minute budget need 1.4 s or less. The model returns to the CPU for saving and validation, so the weights and threshold suit the CPU evaluator |
| 2026-11-07 | Detector training saves a checkpoint each epoch and resumes from it | A low-memory kill cost 82 minutes because weights were saved only at the end |
| 2026-11-06 | Use Superpowers (official marketplace version) for focused debugging, testing and code review when useful; skip its brainstorming and writing-plans; ask before separate worktrees or subagents (rules in `CLAUDE.md`) | `docs/phases.md`, `docs/rules.md` and approval in Plan Mode stay the one project workflow |

## Mocks and stubs in use

- Station geometry, bearings and acoustic direction: simulated
- Pickets: simulated
- Zoom camera: crop from high-resolution clip
- Hand-off: JSON export only
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
- CPU timing against the plan: inference at 4 and 1 threads meets 1,000 frames on both cameras. Short: tracker, 976 looks on thermal and 642 on RGB; decode, one value per clip (55 and 36, covering 4,215 and 2,762 kept frames), so its p50 and p95 are per clip; audio, 3,130 windows but a single thread setting the report does not name, and WAV reading untimed. Validation alone closes these only with new code: one pass gives 964 and 584 looks, decode needs per-frame timing, and audio needs a thread setting. `evaluate_media.py --split val` is the wrong tool, because it appends to `attempts.jsonl` and labels its report HELD-OUT
- The audio classifier does not beat its baseline: 0.750 clean against 0.773 for always answering `engine`, which is 34 of 44 test clips. Nine engine clips are called background
- Sustained live inference is unproven: S2 with all three models keeps real time (125 s wall clock, check 18) only through a per-frame memo. By calculation, 6 unmemoised streams at one look per 0.6 s need about 864 ms of CPU per simulated second (RGB 82.5 ms and thermal 90.3 ms at 4 threads)
- The CUDA path has run for real: the user's T4 completed 20 epochs, and its weights load and evaluate on this CPU. Whether that run resumed is not recorded, so resuming on a GPU stays unproven. No CPU run of thermal exists to compare with
- The manifest hash depends on line endings: `bc49b46d` on Windows with `autocrlf`, `ba662739` for the committed bytes. A fresh Linux clone would have its weights refused by `evaluate_media.py`, so Colab must use a ZIP built with `git archive` on the Windows machine. Worth fixing before Phase 6's second-machine check
- This laptop has 7.7 GB of RAM, and long training competes with everything else open. The training time budget is wall clock, so it also counts sleep
- S4's dust reduces simulated range but is not applied to the frames
- The simulator's 800 m RGB range for a quadcopter is a start value this footage cannot support: the dataset's Distant bin starts at 60 m
- The engine class is mostly road vehicles: a proxy, not evidence of detecting a one-way attack drone
- The dataset has no fixed-wing drone, so S1 camera bearings have no real look evidence
- Phase 3: `Track.status` has no `sector` value though `design.md` A6 needs one; A6 also uses `scipy`, which is not in the `architecture.md` stack, so expect a dependency request
- Phase 4: `design.md` A10 does not say which range or grid coverage uses, and S4's result depends on it. Paper calculation at S4's visibility 0.5: `important` zone with quadcopter RGB range gives 100% clear and 55% in dust (works); perimeter with attack drone RGB stays at 100% (warning never fires); perimeter with quadcopter RGB is 45% even in clear air (warning always on)

## Measured results

### Recorded media, held-out split (`scripts/evaluate_media.py`, `runs/eval/`)

- **RGB detector** (weights `7aa15d48`, threshold 0.15 from validation, second evaluation of these weights on test): drone clips confirmed 17 of 17 (95% interval 0.816 to 1.000); other clips with a false drone track 7 of 19 (0.191 to 0.590); median 1.2 s to confirm. Drone frames: precision 0.805, recall 0.837, and 0.673, 0.700 at IoU 0.5. Drone miss rate: close 0.283, medium 0.159, distant 0.085. Inference mean 82.5 ms at 4 threads, 102.4 ms at 1
- **Audio classifier** (weights `2457d275`, first evaluation on test, 44 clips; the engine class is a proxy): accuracy 0.750 clean (0.606 to 0.854), then 0.750, 0.636, 0.523, 0.273 at +20, +10, 0, -10 dB. Misses 9, 9, 13, 18, 31; false detections 0 throughout. 4.1 ms per 1 s window
- **Thermal detector** (weights `0fc7c5a1`, trained on a Tesla T4, threshold 0.2 from validation, first evaluation on test, run on this laptop's CPU): drone clips confirmed 24 of 24 (95% interval 0.862 to 1.000); other clips with a false drone track 6 of 31 (0.092 to 0.363); median 1.2 s to confirm. Drone frames: precision 0.792, recall 0.897, and 0.721, 0.817 at IoU 0.5. Drone miss rate: close 0.189, medium 0.065, distant 0.072 (validation: 0.275, 0.05, 0.757). False detections 1,355 in 3,459 frames, including 85 drone boxes on bird, airplane or helicopter clips. Inference mean 90.3 ms at 4 threads, 104.4 ms at 1

### Hybrid S2 run (simulated geometry, real model output on held-out clips; not a detection rate)

- Seed 7, all three models: digest `sha256:134cb33f6b12005771cf400130813388c678112cc3ed483c90833f0cda5299c0`. Two fast runs and one real-time run are byte-identical
- Counted from the saved output with a one-off script, not the metrics script: bearings with non-zero drone confidence, RGB 1,121 of 1,127 and thermal 736 of 820. Acoustic top class on 80 bearings: `electric_drone` 64, `background` 12, `engine` 4

### Simulator (`cuas.metrics.evaluator`; simulator results, not real-world performance)

- S2 seed 7: 2,027 bearings from 3 stations, quad-1 seen st1=853, st2=658, st3=516. Geometry is identical with and without recorded media

## Open questions (copy of `prd.md` §10, tick when answered)

- [x] First site type for the demo: oil and gas or stadium? **Stadium: S2, a fictional stadium, opens the walkthrough (2026-11-06)**
- [ ] Dashboard language: English, Arabic or both?
- [x] Acceptable detector licence for the client demo? **For now, permissive only: BSD-3-Clause SSDLite; counsel to review the weights before delivery (2026-11-06)**
- [ ] GPU laptop available for the live demo?

## Session log (newest first)

### 2026-11-06 to 11-07 — Phase 2, in progress
- Done: RGB and thermal detectors, tracker, M-of-N, audio classifier, SNR mixing, hybrid link, recorder, opt-in CUDA training and all three test reports. Every check that can run before merging passes on `ff71287`: 546 tests pass with none skipped, and a fresh clone with no data or models gives 526 passed, 20 skipped. All planned sabotage checks were caught; 2 extra probes of the all-model S2 test were not, which led to two new tests that catch 9 of 9.
- Decisions: see the log above. Stricter scene-based splits replaced neighbouring clip numbers after a leak check.
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
