# Known issues

Everything from `REVIEW.md` (2026-11-14) not fixed before the 2026-11-16 demo, each with a workaround for the demo or "next sprint". Fixed items are listed at the end. The full record is in `docs/memory.md` (Known issues).

## Affects the demo

| Issue | Workaround or plan |
| --- | --- |
| No "Running slower than real time" notice. A recorded-media run can lag silently: S2 at 2× fell up to 1.4 s behind on its first run (2026-11-14), and recorded-media S3 has run up to 4.6 s behind early on. The clock already measures the lag (`SimClock.behind_s`) | Run recorded media at 1× or 2×, close other apps. Next sprint: `behind_real_time` on the `run` message and a top-bar notice |
| S3 with Recorded media alerts on birds: 4 to 10 false alerts per run (5 seeds). Cause: the detectors give some bird clips drone looks (Phase 2's false drone tracks) | Run S3 on the simulator only. Next sprint: require movement and look to agree, or M-of-N looks, before amber or red; report bird alerts per run over 5 seeds before and after |
| Labels crowd near the stations at the full map view (site, station, track and zoom labels overlap) | Tick **Close-up**. Next sprint: spread labels |
| S1 shows only picket wedges for its first minute; tracks confirm from 01:06 | Run S1 at 5× |
| S3 draws ghost and duplicate bird tracks (26 confirmed tracks for 13 targets; p95 position error 100 m) | Say so; none of them alerts. Next sprint, with the bird fix |
| S2 re-acquires its target under a new track ID on 2 of 22 seeds (not the default seed 2002) | Use the default seed |
| At 1366×768 the selected-alert panel scrolls to reach the audio rows | Browser zoom 90%, or use 1920×1080 |
| A card's very first frame can show no evidence record yet; it reads "Evidence record being written…" and the next frame shows the record | None needed: the keeper writes the record automatically |
| Replays carry no evidence: cards read "No evidence kept: replayed stream", and Confirm or Export answer 409 | Use live runs in the demo |
| Audio checked as playing in headless Chrome, but never heard by us | Test the speakers before the meeting |
| S5 has no detector clip (no fixed-wing footage exists in the public data) and shows a coverage banner in fog | Say so if S5 is shown |
| The Zoom tab on big-drone cues (S1, S5) plays one stand-in clip: the same 7 s of an RQ-7B Shadow for every attack drone, whatever its range, direction or the weather; the aircraft flies away from the camera, and the loop fades out and back in at its end. No detector ran on it | Say it is a stand-in (wording in `docs/demo_run_order.md`). The caption and STAND-IN tag are on screen. Next sprint: real fixed-wing footage through the detector |
| The stand-in clip is not in git (`data/standin/`, 248 KB) and no script rebuilds it; `config/standin_media.yaml` records the source, the cut and the hash. Without the file the Zoom tab shows the simulated view | Use this laptop; add `data/standin/` to the private backup zip |
| The page fetches the stand-in listing once, when it loads, like the basemap | Reload the page (F5) if the Zoom tab reads "(simulated)" although the server printed a stand-in clip |
| Around 01:51 in S1 the zoom camera loses a drone passing 230 to 310 m from st1 (6 to 9° off its pointing, in a 2° view). The tab now reads "Zoom slewing to target"; before 2026-11-15 it drew a large bright blob in the corner | Wording in `docs/demo_run_order.md`. The zoom scheduler itself is unchanged |
| Big-drone camera cues match by direction only: a camera bearing within 30° of the cued picket counts, because picket bearings err by about 20°. In S1 a cue can be "found" by another drone of the same wave; in S5 (one drone) a second picket's cue is also marked detected by a different station's bearing of the same drone | Show S1 only; the panel and evidence say "camera detection", never which drone. Next sprint: match a camera bearing to a cue through the tracker |
| The page fetches the basemap once, when it loads. If the server did not answer then (a tab reopened before the server started), the map shows the grid and "local grid 500 m (no basemap)" until the page is reloaded | Press F5 once the server shows "AI models ready". Next sprint: fetch the basemap again on reconnect |
| The reference page (`/reference/`) still captions clips as "st1.rgb at 12.3 s" | Do not open it in the demo. Next sprint: same caption as the operator dashboard |
| Recordings and models are not in git; on another machine recorded media is unavailable, and on Linux the media manifest hash changes with line endings | Use this laptop; the private backup zip restores `data/` and `models/`. Next sprint: `.gitattributes` for the manifest |
| The commit history carries the author's personal email | Do not give the client repository access. Next sprint: noreply address for new commits |

## Not built (gaps against the client brief)

| Gap | Status |
| --- | --- |
| Detection at 15 km, classification at about 10 km | Not shown. Simulator start values are up to 3 km (cameras) and 1.5 km (microphones). Next sprint: projected long-range scenario, clearly labelled |
| Interceptor status, response recommendations, human authorisation, override, emergency abort | Not built. `docs/rules.md` §7: detect and report only. Needs an explicit decision before any work |
| Telling drones from aircraft | Not built: no aircraft in any scenario; the detector's airplane class is weak (precision 0.307). Next sprint: mock ADS-B scenario |
| Sensor health that can fail | Simulated sensors always report OK (now tagged SIM). Next sprint: fault injection in a scenario |
| Audit trail with wall-clock time and operator name | Records carry simulated time only. Next sprint: login field, UTC time, event log strip |
| Human-readable incident report | The hand-off is JSON only. Next sprint: one-page HTML report |
| The hand-off package says "mock" but not "simulated" | Say so when showing it. Next sprint: a `simulated` field |
| Site at our lab location | Not done; the map is Portsmouth with a fictional site. Next sprint |
| Track trails of 30 s, detection boxes drawn on the clips | Trails are 20 s; no boxes. Next sprint |

## Code (next sprint)

| Issue | Where |
| --- | --- |
| No JavaScript tests for the operator page; checked by Python wording tests and headless screenshots only | `src/cuas/dashboard/static/app/` |
| The clock counts a tick before honouring a pause, so labels made while paused are stamped up to 0.2 s ahead | `src/cuas/clock.py`, `tick()` |
| `assert` used for runtime checks | `src/cuas/dashboard/server.py` (export and request paths) |
| Training loads checkpoints without `weights_only=True` | `scripts/train_detector.py` |
| No Origin check on the WebSocket (local only today) | `src/cuas/dashboard/server.py`, `/ws` |
| `prd.md` time to alert (red within 5 s) is missed in the simulator | `docs/memory.md` |

## Fixed on 2026-11-14

Zoom view: a target outside the zoom field of view is no longer clamped to the frame edge and drawn as a blob; the frame says "Zoom slewing to target" (2026-11-15). Big-drone video sequence for S1 and S5: acoustic only, then a SIMULATED camera view at the first camera detection (logged as a `camera_detection` evidence record), then the zoom view (2026-11-15). Stop button and `POST /api/run/stop`; models loaded once at server start with progress, and Start waits for them; a failed run says so (`ended_reason`); buttons no longer stick when the server is unreachable; the operator dashboard is pushed and tagged; video and audio captions name the public dataset and say the clip is not this track; "Zoom (stand-in clip)"; SIM tags with a legend on simulated confidence and health; confidence capped at 99%; INSIDE ZONE replaces a 0 s TTI; label and export requests time out (504) and one bad request no longer stops the evidence keeper; the Acoustic detections panel lists every acoustic event the map and alerts use.
