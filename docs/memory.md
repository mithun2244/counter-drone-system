# Memory — project state

> The project's notebook. **Read it at the start of every session. Update it at the end.**
> Keep it short: the newest status at the top, old detail trimmed into one-line summaries.

## Current status

- **Current phase:** Phase 0 — Project setup
- **Last session:** (none yet)
- **Next step:** create the folder layout and `pyproject.toml` (see `phases.md` Phase 0)

## Decisions log

| Date | Decision | Why |
| --- | --- | --- |
| 2026-11-06 | Sensors: RGB, thermal, zoom PTZ, acoustic arrays, Remote ID, acoustic pickets; no radar or RF | Client constraint; passive-only design |
| 2026-11-06 | Demo = simulator for geometry + real AI on public recordings | No hardware yet; proves the pipeline end to end |
| 2026-11-06 | Single Python process, asyncio, in-process bus behind an interface | Simple for the demo; swappable for a network bus later |
| 2026-11-06 | Messages inspired by SAPIENT (detections and tracks, not raw video) | Matches the real system's ingest gateway |
| 2026-11-06 | Kalman filter on triangulated positions first; bearing EKF/IMM later | Simpler to build and test |
| 2026-11-06 | Detect and report only; no mitigation code | Legal scope in Saudi Arabia; authorities act |

## Mocks and stubs in use

- Station geometry, bearings and acoustic direction: simulated
- Pickets: simulated
- Zoom camera: crop from high-resolution clip
- Hand-off: JSON export only
- National air picture: not in the demo

## Known issues and risks

- YOLO (Ultralytics) is AGPL-3.0: licence or swap before client delivery
- Dataset licences not yet checked
- All speeds, ranges and thresholds are start values to tune

## Open questions (copy of `prd.md` §10, tick when answered)

- [ ] First site type for the demo: oil and gas or stadium?
- [ ] Dashboard language: English, Arabic or both?
- [ ] Acceptable detector licence for the client demo?
- [ ] GPU laptop available for the live demo?

## Session log (newest first)

<!-- Template:
### YYYY-MM-DD — Phase N
- Done:
- Decisions:
- Issues / mocks added:
- Next step:
-->
