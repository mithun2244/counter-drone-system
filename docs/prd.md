# PRD — C-UAS Detection Demo

> Product Requirements Document. Explains **what** we are building for the demo and **why**.
> How it is built lives in `architecture.md` and `design.md`.

## 1. Problem

Sites in Saudi Arabia (oil and gas, power, stadiums, events) face two drone threats:

- **Fast one-way attack drones** (fixed wing, loud engine, about 50 m/s, often in waves).
- **Small quadcopters** (DJI size, about 0.3 m, about 15 m/s, easy to confuse with birds).

Our real system will detect them using only **cameras and microphones**: no radar and no RF sensors.
Before building hardware, we need a **software demo** that proves the idea works end to end and can be shown to the client.

## 2. Goal of the demo

Show, on one computer, the full chain:

**sense → detect → triangulate → classify → rank threat → alert → record evidence**

Use real AI models on real recordings, plus a simulator for the parts that need hardware we don't have yet (several stations, pickets, zoom cameras).

## 3. Users

| User | What they need from the demo |
| --- | --- |
| Client security manager | See that real threats are caught early and birds are ignored |
| Operator (future) | A clear, ranked alert list with a video clip per alert |
| Our engineering team | A codebase that grows into the real system without a rewrite |

## 4. Scope

### In scope (demo)

- A scenario **simulator**: site map, 3 ground stations, an outer ring of acoustic pickets, drone and bird flight paths.
- **Real video AI**: drone detection and tracking on recorded RGB and thermal clips.
- **Real audio AI**: a drone/no-drone and engine-type classifier on recorded audio clips.
- **Shared tracker**: triangulates bearings from 2 or more stations into a 3D position, and follows several targets at once.
- **Classifier fusion**: combines look, movement and sound into one probability per track.
- **Threat ranking**: zones plus time-to-impact give a score and a level (red, amber, info).
- **Zoom scheduler**: assigns simulated zoom cameras to the most dangerous tracks.
- **Visibility model (simple)**: a dust/visibility setting per scenario that reduces camera range.
- **Dashboard**: site map, live tracks, ranked alert queue, alert clip, coverage status.
- **Evidence store**: every alert saved with a clip and a SHA-256 hash, plus a tamper-evident log.
- **Mock hand-off**: export of an alert package as JSON (no real connection to authorities).

### Out of scope (demo)

- Real cameras, microphones, masts, PTP time sync hardware.
- Any mitigation (jamming, takeover). The real system never does this.
- Real connection to MOI, PSS, MoD or the national air picture (mock only).
- NCA ECC/OTCC certification, Camera Law approval, production security.
- Client data. The demo uses **public data only**.

## 5. Demo scenarios (must all run)

| ID | Scenario | What it proves |
| --- | --- | --- |
| S1 | Wave of 3 attack drones toward the processing unit | Early warning from pickets, multi-target tracking, red alerts ranked by time-to-impact |
| S2 | One quadcopter over a fictional stadium | Small-target detection, zoom confirmation, triangulation |
| S3 | Flock of birds plus one quadcopter | Birds rejected, only the drone alerted |
| S4 | S2 during a dust storm | Visibility model lowers coverage and the dashboard warns the operator |

The client walkthrough opens with S2. All scenario sites are fictional. They share one site geometry, zone IDs and zone weights; display labels come from each scenario's metadata (industrial for S1, stadium for S2, S3 and S4).

## 6. Functional requirements

| ID | Requirement |
| --- | --- |
| FR-1 | The simulator produces time-stamped flight paths for drones and birds from a YAML scenario file |
| FR-2 | Each simulated station produces bearing detections (azimuth, elevation, uncertainty) for targets in its view |
| FR-3 | The video detector runs on recorded clips and outputs boxes, track IDs and confidence |
| FR-4 | The audio classifier runs on recorded clips and outputs drone / no-drone and engine type with confidence |
| FR-5 | Pickets raise an early alert when a loud target passes within their hearing radius |
| FR-6 | The gateway accepts only valid messages (schema, timestamp, known sensor) and logs rejected ones |
| FR-7 | The tracker triangulates targets seen by 2 or more stations and keeps one track per target |
| FR-8 | The classifier fusion outputs P(drone), P(bird), P(attack drone) per track |
| FR-9 | Threat ranking outputs a score from 0 to 1 and a level per track, sorted highest first |
| FR-10 | The zoom scheduler assigns zoom cameras per station, highest threat first (`zoom_per_station`: 0, 1 or 2; default 1) |
| FR-11 | The dashboard updates live (at least 2 times per second) |
| FR-12 | Every red or amber alert is stored with a clip, metadata and a hash |
| FR-13 | One command runs any scenario end to end |
| FR-14 | After each run, a metrics report is written (detections, false alarms, warning time, position error) |

## 7. Non-functional requirements

- Runs on one laptop. A GPU is optional; the demo must still run on CPU at reduced frame rate.
- Same scenario plus same seed gives the same result (reproducible).
- Each scenario runs in under 5 minutes.
- Code is modular so a simulated part can be replaced by real hardware later without changing other parts.

## 8. Success metrics (demo targets, measured in the simulator)

| Metric | Plain meaning | Demo target |
| --- | --- | --- |
| Detection rate | Simulated drones that become a confirmed track | ≥ 95% in S1–S3 |
| False alarms | Red or amber alerts with no real drone | 0 in S3 |
| Early warning | Seconds from first picket alert to arrival (S1) | ≥ 45 s |
| Position error | Distance between triangulated and true position | ≤ 20 m median |
| Time to alert | Seconds from first 2-station detection to red alert | ≤ 5 s |

These are simulator numbers. They do not prove real-world performance.

## 9. Assumptions

- Public datasets are allowed for a demo (licences to be checked; see `rules.md`).
- The site map is fictional but realistic: 3 stations about 500 m apart, pickets about 3 km out.
- Speeds and hearing ranges are approximate engineering estimates.

## 10. Open questions

- [x] Which site type should the demo show first: oil and gas (S1) or stadium (S2)? **Decided 2026-11-06: stadium. S2, on a fictional stadium, opens the client walkthrough.**
- [ ] Does the client want the dashboard in Arabic, English or both?
- [ ] Which detector licence is acceptable for a client demo? (Ultralytics YOLO is AGPL-3.0.)
- [ ] Is a GPU laptop available for the live demo?
