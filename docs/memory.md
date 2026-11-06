# Memory — project state

> The project's notebook. **Read it at the start of every session. Update it at the end.**
> Keep it short: the newest status at the top, old detail trimmed into one-line summaries.

## Current status

- **Current phase:** Phase 1 — Messages, bus, clock, simulator (not started)
- **Last session:** 2026-11-06, finished Phase 0
- **Next step:** plan Phase 1 and get approval, starting with the Pydantic schemas from `architecture.md` §4
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
| 2026-11-06 | Develop on Python 3.11 (`.python-version`); `requires-python >=3.11` | Follows `phases.md` and tests the lowest supported version; numpy 2.5 needs 3.12, so 3.11 locks numpy 2.4.6 |
| 2026-11-06 | S2, a fictional stadium, opens the client walkthrough; geometry, zone IDs and weights are shared, display labels live in scenario metadata | Client walkthrough choice; one site file serves every scenario, with no fallback that could show industrial labels at the stadium |
| 2026-11-06 | Ground truth stays in `cuas.sim`, and only `cuas.metrics` reads it; it never goes on the bus | An evaluator must be able to score the pipeline without the pipeline seeing the answers |
| 2026-11-06 | `zoom_per_station` is 0, 1 or 2, default 1, in `site.yaml` with a `--zoom-per-station` override; unused until Phase 4 | The paired S3 comparison in Phase 4 needs runs that differ only in this value |
| 2026-11-06 | Scenario `seed` drives sensor noise, target `seed` fixes the flight path, one named random stream per sensor and target | Paired runs fly the same routes, and a change to one sensor cannot disturb another's noise |
| 2026-11-06 | `site.yaml` read as plain YAML; camera specs and `base_range` not added yet | Typed `SiteConfig` and those values wait for Phase 1, the first phase to use them |
| 2026-11-06 | Folders only in Phase 0: no `clock.py`, `control/*.py` or `download_data.py` yet | They arrive in their own phases, with tests (`rules.md` §1, §3) |

## Mocks and stubs in use

- Station geometry, bearings and acoustic direction: simulated
- Pickets: simulated
- Zoom camera: crop from high-resolution clip
- Hand-off: JSON export only
- National air picture: not in the demo

## Known issues and risks

- YOLO (Ultralytics) is AGPL-3.0: licence or swap before client delivery
- Dataset licences not yet checked
- All speeds, ranges and thresholds are start values to tune; so are the `site.yaml` mast heights and zone sizes, which the docs do not specify
- `nvidia-smi` is not available on the dev machine, so it probably has no NVIDIA GPU; this affects Phase 2 training and the open GPU question
- Phase 2: `design.md` A2 has the station pick a clip "of the same class". The simulator must pick the clip and pass only the clip, or ground truth leaks into `station/`
- Phase 3: `Track.status` has no `sector` value though `design.md` A6 needs one; A6 also uses `scipy`, which is not in the `architecture.md` stack, so expect a dependency request
- Phase 4: `design.md` A10 does not say which range or grid coverage uses, and S4's result depends on it. Paper calculation at S4's visibility 0.5: `important` zone with quadcopter RGB range gives 100% clear and 55% in dust (works); perimeter with attack drone RGB stays at 100% (warning never fires); perimeter with quadcopter RGB is 45% even in clear air (warning always on)

## Open questions (copy of `prd.md` §10, tick when answered)

- [x] First site type for the demo: oil and gas or stadium? **Stadium: S2, a fictional stadium, opens the walkthrough (2026-11-06)**
- [ ] Dashboard language: English, Arabic or both?
- [ ] Acceptable detector licence for the client demo?
- [ ] GPU laptop available for the live demo?

## Session log (newest first)

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
