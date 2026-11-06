# Memory — project state

> The project's notebook. **Read it at the start of every session. Update it at the end.**
> Keep it short: the newest status at the top, old detail trimmed into one-line summaries.

## Current status

- **Current phase:** Phase 2 — Station AI (not started)
- **Last session:** 2026-11-06, finished Phase 1
- **Next step:** plan Phase 2 and get approval, including the new dependencies and dataset licences it needs (`rules.md` §4, §5)
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
| 2026-11-06 | Recordings: Svanström dataset, excluding its 49 YouTube clips and helicopter audio; FSD50K CC0 `Engine` clips as a proxy | Their rights are unverified; the Drone Audio Dataset bars defence and surveillance use (`data/README.md`) |
| 2026-11-06 | Split by scene group: neighbouring clip numbers sharing bin and drone type, joined with clips whose signatures are within 32 of 256 bits | The dataset has no session IDs, and neighbouring numbers alone left 15 of 38 RGB test clips with a near-identical training clip. Still a stand-in that cannot prove two groups are separate flights |
| 2026-11-06 | Clips are matched to simulated range; M-of-N does not drop bearings | Mixing all bins would overstate results; keeping geometry leaves Phase 1 bearings identical |
| 2026-11-06 | Use Superpowers (official marketplace version) for focused debugging, testing and code review when useful; skip its brainstorming and writing-plans; ask before separate worktrees or subagents (rules in `CLAUDE.md`) | `docs/phases.md`, `docs/rules.md` and approval in Plan Mode stay the one project workflow |

## Mocks and stubs in use

- Station geometry, bearings and acoustic direction: simulated
- Pickets: simulated
- Zoom camera: crop from high-resolution clip
- Hand-off: JSON export only
- Bearing `class_probs` and `snapshot_ref`: empty until Phase 2
- Picket engine guess and loudness: noisy simulated values (`sim/picket.py`) until Phase 2
- Sensor health: simulated sensors never report a fault
- National air picture: not in the demo

## Known issues and risks

- Before client delivery: counsel review of weights and recording rights; the to-do list is in `data/README.md`
- All speeds, ranges and thresholds are start values to tune; so are the `site.yaml` mast heights, zone sizes, `p0` values, base ranges, tick and picket settings, which the docs do not specify
- Determinism is proven for the same lockfile on the same machine, not byte for byte across machines; Phase 6's second-machine check should compare behaviour
- `nvidia-smi` is not available on the dev machine, so it probably has no NVIDIA GPU; this affects Phase 2 training and the open GPU question
- SSDLite's coarse features may miss small targets; 85% of thermal drone clips show targets 15 px wide or smaller
- The simulator's 800 m RGB range for a quadcopter is a start value this footage cannot support: the dataset's Distant bin starts at 60 m
- The engine class is mostly road vehicles: a proxy, not evidence of detecting a one-way attack drone
- The dataset has no fixed-wing drone, so S1 camera bearings have no real look evidence
- Phase 3: `Track.status` has no `sector` value though `design.md` A6 needs one; A6 also uses `scipy`, which is not in the `architecture.md` stack, so expect a dependency request
- Phase 4: `design.md` A10 does not say which range or grid coverage uses, and S4's result depends on it. Paper calculation at S4's visibility 0.5: `important` zone with quadcopter RGB range gives 100% clear and 55% in dust (works); perimeter with attack drone RGB stays at 100% (warning never fires); perimeter with quadcopter RGB is 45% even in clear air (warning always on)

## Open questions (copy of `prd.md` §10, tick when answered)

- [x] First site type for the demo: oil and gas or stadium? **Stadium: S2, a fictional stadium, opens the walkthrough (2026-11-06)**
- [ ] Dashboard language: English, Arabic or both?
- [x] Acceptable detector licence for the client demo? **For now, permissive only: BSD-3-Clause SSDLite; counsel to review the weights before delivery (2026-11-06)**
- [ ] GPU laptop available for the live demo?

## Session log (newest first)

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
