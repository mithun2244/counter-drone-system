# Phases — C-UAS Detection Demo

> Build the demo in small, testable steps. Finish one phase, run its checks, commit, then update `memory.md`.
> Each phase is sized for about 1 to 3 Claude Code sessions.

---

## Phase 0 — Project setup

**Goal:** an empty but working project skeleton.

Tasks:
- [x] Create the folder layout from `architecture.md` §3
- [x] `pyproject.toml` with `uv`, Python 3.11, `ruff`, `pytest`, `pytest-asyncio`, `pydantic`, `numpy`, `pyyaml`
- [x] `.gitignore` for `data/`, `models/`, `runs/`, `.venv/`
- [x] `config/site.yaml` with 3 stations (about 500 m apart), 8 pickets on a 3 km ring, 3 zones (critical, important, perimeter)
- [x] `scripts/run_demo.py` that prints "hello" and loads `site.yaml`

Done when:
- [x] `uv run pytest` passes (one smoke test)
- [x] `uv run ruff check .` is clean
- [x] `uv run python scripts/run_demo.py` loads the site config

---

## Phase 1 — Messages, bus, clock, simulator

**Goal:** fake targets fly over the site and stations produce bearings.

Tasks:
- [x] Pydantic schemas for every message in `architecture.md` §4
- [x] Bus interface plus an in-process `asyncio.Queue` implementation
- [x] Simulated clock (real-time or fast mode)
- [x] Scenario loader and trajectory models (attack drone, quadcopter, bird, friendly drone)
- [x] Station simulation: field of view, range, detection probability, bearing noise (`design.md` A2)
- [x] Picket simulation (`design.md` A2)
- [x] Scenario files `s1`–`s4` (`prd.md` §5)

Done when:
- [x] Unit tests: bearing from a known position equals the expected angles; nothing is detected outside the range
- [x] Running S1 in fast mode prints bearings from 3 stations and picket alerts, and is the same every run with the same seed

---

## Phase 2 — Station AI (real models)

**Goal:** real detectors turn real clips into look and sound confidences.

Tasks:
- [x] `scripts/download_data.py` plus `data/README.md` (dataset, URL, licence)
- [x] Video detector wrapper (SSDLite320, see `architecture.md` §6), ByteTrack-style tracker, M-of-N confirmation (`design.md` A3)
- [x] Fine-tune or evaluate the detector on drone vs bird clips; save weights in `models/`
- [x] Audio classifier: mel-spectrogram plus small CNN (drone / no-drone, engine type); train and save
- [x] SNR mixing by distance and wind (`design.md` A2)
- [x] Hybrid link: a simulated detection pulls a real clip and runs the real models
- [x] Local recorder with a SHA-256 hash per file

Done when:
- [x] Detector evaluation report in `runs/eval/` (precision, recall on a held-out set)
- [x] Audio classifier accuracy on a held-out set is reported (no target; just measured honestly)
- [x] S2 runs and bearings carry real `class_probs`

---

## Phase 3 — Gateway and shared tracker

**Goal:** bearings from several stations become 3D tracks.

Tasks:
- [x] Gateway validation and rejection log (`design.md` A4)
- [x] Triangulation with the angle and closest-distance checks (`design.md` A5)
- [x] Association (Hungarian), track birth, Kalman filter, track status (`design.md` A6)
- [x] Acoustic-only sector tracks from pickets

Done when:
- [x] Unit test: two perfect rays give the exact point; near-parallel rays are rejected
- [x] S1: three attack drones give exactly 3 confirmed tracks, no duplicates
- [x] Median position error ≤ 20 m in S1 and S2 (from the metrics script)

---

## Phase 4 — Decision layer

**Goal:** each track gets a class, a threat score and a zoom camera.

Tasks:
- [ ] Behaviour features and rules (`design.md` A7)
- [ ] Log-odds fusion of look, move and sound
- [ ] Threat ranking with zones, TTI, approved flights and reasons (`design.md` A8)
- [ ] Zoom scheduler with dwell and pre-emption (`design.md` A9)
- [ ] Paired S3 comparison: same seed at `zoom_per_station` 0, 1 and 2, reported by the metrics script
- [ ] Visibility model and coverage % (`design.md` A10)

Done when:
- [ ] S3: birds never reach amber or red; the quadcopter reaches red
- [ ] S1: the three red alerts are ordered by TTI
- [ ] S4: coverage drops below 80% and the warning flag is set
- [ ] Unit tests for the threat score formula with hand-calculated cases

---

## Phase 5 — Dashboard and evidence

**Goal:** the operator view and tamper-evident records.

Tasks:
- [ ] FastAPI app plus WebSocket stream of tracks, alerts and status
- [ ] Map canvas, alert queue, clip panel, status panel (`design.md` B1–B4)
- [ ] Confirm / Dismiss buttons saved as labels
- [ ] Evidence store, hash chain, `cuas verify` command, hand-off JSON export (`design.md` A11)

Done when:
- [ ] The dashboard updates at least 2 times per second during S1
- [ ] Editing any stored file makes `cuas verify` fail
- [ ] Export produces a valid JSON package per alert

---

## Phase 6 — Demo polish and report

**Goal:** a smooth, repeatable client demo.

Tasks:
- [ ] Metrics report per run (`prd.md` §8) written to `runs/<id>/metrics.md`
- [ ] One command per scenario plus a "full demo" playlist (`design.md` B6)
- [ ] README with setup, run and troubleshooting steps
- [ ] Dry run on the demo laptop (CPU and GPU)

Done when:
- [ ] All 4 scenarios run end to end, each in under 5 minutes
- [ ] The metrics report meets or honestly reports against every `prd.md` §8 target
- [ ] A fresh clone, then setup, then demo works on a second machine

---

## Later (not in the demo)

Bearing-level EKF/IMM, swarm mode (GM-PHD), real camera and microphone nodes, network bus, PTP, real hand-off, NCA ECC/OTCC controls, Camera Law-compliant evidence storage, in-Kingdom learning loop.
