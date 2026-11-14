# Pre-demo review: C-UAS detection demo

Review date: 2026-11-14. Branch `phase-5-operator-dashboard` at `2bb90c3`, clean tree. Reviewer: Claude Code. No code was changed; this file is the only addition.
Client brief reviewed against: Haris Unmanned Systems (critical-infrastructure counter-UAV).

## Status after fixes (2026-11-15, tag `demo-final-2026-11-15`)

The review below is kept as written on 2026-11-14. Since then:

| Review item | Status |
| --- | --- |
| Risk 1: dashboard only on this laptop | **Fixed**: branch pushed, tags `demo-backup-2026-11-14`, `stage1-2026-11-14`, `demo-final-2026-11-15`; processed basemap committed; private zip of `data/` and `models/` |
| Risk 2: S3 with recorded media alerts on birds | **Not fixed**. Workaround: S3 on the simulator only (`docs/demo_run_order.md`) |
| Risk 3: a run cannot be stopped | **Fixed**: Stop button and `POST /api/run/stop` |
| Risk 4: model loading freezes the page; silent lag | Loading **fixed** (once, at server start, with progress). Lag notice **not done**: run recorded media at 1× or 2× |
| Risk 5: only this laptop has the media | **Not fixed** (licences, size). Workaround: this laptop, or restore from the private zip |
| Risk 6: things that look wrong live | Partly: INSIDE ZONE added; label crowding, S1's slow start and S3 ghost tracks have workarounds in `docs/known_issues.md` |
| Risk 7: buttons stick on "Saving…" | **Fixed** |
| Honesty 1 and 2: video captions, "Zoom" | **Fixed**: "Sample clip from <dataset> - not footage of this track", "Zoom (stand-in clip)", "Sample recording from <dataset>", from the media manifest |
| Honesty 3 and 4: health ticks, confidence | **Fixed**: SIM tags and a legend; confidence capped at 99% |
| Honesty 5: hand-off says mock, not simulated | Not fixed; next sprint |
| Honesty 6 and 7: caveats and missed targets | Covered by `docs/client_results_sheet.md` |
| Code issues 1 to 5 (request hang, fetch errors, Stop, failed run, model loading) | **Fixed**, with tests |
| Code issues 6 to 10 | Not fixed; next sprint (`docs/known_issues.md`) |
| Brief gaps: 15 km, interceptor and authorisation, aircraft, audit trail, incident report | Not built; listed as gaps in `docs/known_issues.md`, with honest answers in `docs/demo_run_order.md` |

Tests after the fixes: 1019 before the deadline plan, 1025 passed (1 known deprecation warning) at the tag; lint clean; S1–S5 control digests unchanged throughout.

## Summary

1. The software is solid for what it is: a deterministic, single-laptop simulator with real detectors and an audio classifier run on public recordings, plus an offline operator dashboard and a tamper-evident evidence chain. Tests 1007 passed (0 skipped), lint clean, all five scenarios run without an error or warning, and repeated runs give identical digests.
2. It does not meet the brief's headline numbers. The longest simulated camera range is 3 km and the longest microphone range 1.5 km, against 15 km detection and about 10 km classification. Real-media accuracy was measured on short-range clips (the dataset's "distant" bin starts at 60 m).
3. The brief's response chain is absent: there are no response recommendations, no interceptor status, no human-authorisation step, no override and no abort. This is deliberate (`docs/rules.md` §7: detect and report only), so it needs a decision on what to say to the client, not a code fix before Monday.
4. Honesty is mostly good: simulator output is labelled, and the measured numbers in `docs/memory.md` give their sources. Four screen items can still mislead a client: unlabelled stand-in video, a "Zoom" tab that is not zoom footage, green health ticks that cannot fail, and percentage confidences with no "simulated" qualifier.
5. The biggest live risks: (a) the operator dashboard exists only on this laptop, because 13 commits are unpushed; (b) S3 with **Recorded media** ticked raises false alerts on birds; (c) a started run cannot be stopped; (d) recorded-media runs stall the server while models load and run close to the real-time limit on this 7.7 GB laptop.

## How to run

Stack: Python 3.11.16 (pinned in `.python-version`), `uv` 0.13.7, `uv_build` backend. Runtime dependencies: numpy, scipy, pydantic, PyYAML, torch 2.15.0 and torchvision 0.29.2 (CPU wheels), PyAV, FastAPI, Uvicorn and websockets. The frontend is plain HTML, CSS and JS with no build step.

Main modules (`src/cuas/`). Components talk only over in-process buses (sensor, ingest, control, evidence):

| Folder | Job |
| --- | --- |
| `sim/` | Scenario loader, trajectories, station and picket models, media link that picks recorded clips by simulated range. Holds ground truth |
| `station/` | Real AI: SSDLite detector, local tracker, M-of-N confirmation, mel features, sound classifier, recorder |
| `gateway/` | Validates messages: schema, timestamp, known sensor |
| `control/` | Triangulation, Kalman filter, association, shared tracker, sectors, classification fusion, threat score, alerts, coverage, zoom scheduler |
| `evidence/` | Hash-chained JSONL store, keeper, hand-off package, verifier |
| `dashboard/` | FastAPI server, WebSocket contract, frame builder, replay, basemap, static operator page (`static/app/`) and reference page |
| `metrics/` | Evaluators that read ground truth (simulator scoring and held-out media scoring) |
| `schemas/` | The bus message types |
| `scripts/` | `run_demo.py` (entry point), `live_runs.py`, data download, training, evaluation, basemap fetch, analysis reports |

Commands (all from `cuas-demo/`):

```sh
uv sync --locked                                          # install
uv run pytest --ignore=tests/test_decision.py            # regular tests (frozen gate excluded on purpose)
uv run ruff check . && uv run ruff format --check .      # lint
uv run python scripts/run_demo.py --scenario s2 --fast   # one scenario, console output
uv run python scripts/run_demo.py --dashboard            # dashboard at http://127.0.0.1:8000/
uv run cuas verify runs/<run_id>                         # check a run's evidence chain
```

Recorded-media mode needs `data/` and `models/`. They are on this laptop but not in git (`scripts/download_data.py`, then training, see `data/README.md`). The Portsmouth basemap needs `data/basemap/portsmouth.json` (`scripts/fetch_basemap.py`, one internet request); without it the map draws a grid.

### What I ran and what it printed

| Step | Result | Time |
| --- | --- | --- |
| `uv sync --locked` | `Resolved 48 packages in 0.99ms` / `Checked 42 packages in 1ms` | 0.05 s (already installed) |
| `pytest --ignore=tests/test_decision.py` | `1007 passed, 1 warning in 302.45s (0:05:02)` | **5 min 15 s**; slowest `test_s2_with_real_models_is_repeatable` 21.75 s |
| `ruff check` / `ruff format --check` | `All checks passed!` / `174 files already formatted` | a few seconds |
| `run_demo.py` (no arguments) | `hello` / `loaded site.yaml: 3 stations, 8 pickets, 3 zones` | 0.7 s |
| S1 `--fast` | 3 confirmed tracks, 3 red alerts, 0 rejected; picket warning 73.8 to 85.8 s | 1.8 s |
| S2 `--fast` | 1 track, 1 red alert; red 43.8 s after its track started | 1.6 s |
| S3 `--fast` | 26 confirmed tracks for 13 targets, **4 false tracks, 2 overlapping and 5 sequential duplicates**, p95 error **100.23 m**; 1 alert, on the drone only | **11.6 s** (slowest scenario) |
| S4 `--fast` | 1 track, 1 red alert, coverage 54.8%, warning set | 0.9 s |
| S5 `--fast` | 1 track, 1 red alert, coverage 21.9%, warning set | 0.8 s |
| S1 twice, S3 twice | identical sensor and control digests (S1 `a7b2cad9…` / `ec779f9b…`, S3 `57b06551…` / `bf4b5d3a…`) | |
| S2 `--fast --recorded-media` (all three real models) | 1 track, 1 red alert, red **5.0 s** after its track started (against 43.8 s simulator-only), no error | 26.1 s including model loading |
| Dashboard (port 8021) | `/api/profiles` 200; starting S2 gives a run; a second start gives `409 a run is already going`; speed 1000 gives `422 Input should be 1, 2 or 5`; `action: stop` gives `422 Input should be 'pause', 'play' or 'speed'`; clip path traversal 404; text/plain POST 422; `/api/basemap` 200, 154 KB | starts in about 1 s |
| `cuas verify runs/s2_seed2002_043` | `verified … 2 records, 6 files, head seq 2` | |
| `cuas verify runs/does_not_exist` | `FAILED … no evidence chain at evidence/chain.jsonl`, exit 1 | |

Errors and warnings printed: none by the scenario runs, lint or the dashboard. The test run printed one warning, from `.venv/Lib/site-packages/fastapi/testclient.py:1` (tests only; an accepted choice in `memory.md`):

```
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
```

Side note: on Windows, `timeout 60 uv run …` killed `uv` but left the Python server running on its port, so I stopped it by PID. Stop the demo server with Ctrl+C in its own window, not by killing `uv`.

## Requirement checklist

| Brief requirement | Status | Where | Notes |
| --- | --- | --- | --- |
| Detection at 15 km, classification at about 10 km, acoustic plus long-range EO | **Missing** | `config/site.yaml` (`base_range_m`: attack drone 3000 m on cameras, 1500 m acoustic; quadcopter 800 / 600 / 300 m; pickets 3 km out, hearing radius 1500 m) | Simulated tracks start 1.6 to 1.8 km out in S1 (`memory.md`, 15° ray rule with 500 m baselines). Real-media results come from the Svanström dataset, whose "distant" bin starts at 60 m. Nothing in the repo supports a 15 km or 10 km claim |
| Tell drones from birds and aircraft | **Partial** | `control/classify.py`, `control/behaviour.py`, `station/detector.py` (classes drone, bird, airplane, helicopter), S3 | Birds: simulator-only S3 gives 0 bird alerts. With recorded media, S3 raises **4 to 10 false alerts per run** on birds (`memory.md`). Aircraft: the detector has the classes, but fusion outputs only P(drone), P(bird) and P(attack drone), no scenario contains aircraft, and thermal airplane precision is 0.307 (recall 0.205) |
| Real-time alerts with direction, estimated location, confidence | **Done (simulator)** | `control/threat.py`, `control/alerts.py`, `dashboard/frames.py`, `static/app/app.js` | Cards show level, class with %, zone, TTI and reasons; the selected alert shows position, altitude, speed and direction. Location is in site-local metres, not lat/long or MGRS. Updates 2.5 times a second (`frame_period_s: 0.4`). Time to alert misses the PRD's own 5 s target in simulator-only runs (S2 red 43.8 s after its track starts; 5.0 s with recorded media, measured from a different start event than the PRD's) |
| Central map console: sensors, tracks, interceptor status | **Partial** | `static/app/map.js`, `index.html` | Stations, pickets, zones, wedges, bearing rays, tracks with trails and zoom tasks are all shown. **Interceptor status is missing**: there is no interceptor concept anywhere in the code |
| Automated response recommendations; interception only after human authorisation; operator override; emergency abort | **Missing** (out of scope by rule) | `docs/rules.md` §7, `docs/prd.md` §4 | The only operator actions are Confirm, Dismiss and Export hand-off JSON (`server.py:319-335`). There is no recommendation, authorisation, override or abort. A run cannot even be stopped (`contract.py:343-345`) |
| Event logging, incident reports, health monitoring, audit trail | **Partial** | `evidence/store.py`, `evidence/keeper.py`, `evidence/handoff.py`, `cli.py`, `sim/station.py:181` | Done: SHA-256 hash chain of alert, escalation, label and export records, with `cuas verify`. Partial: the "incident report" is a JSON hand-off file, with no human-readable report. Records carry only simulated time, with no wall-clock time and no operator identity. Health: `SensorStatus` is always `ok=True` (`# MOCK`), there is no process or CPU health, and no `logging` configuration, so INFO logs are dropped |
| Separate demonstrated (measured) from simulated or projected | **Partial** | `docs/memory.md` (Measured results), evaluator's `simulator results, not real-world performance`, map notice `Simulated scenario: …`, `prd.md` §8 | The internal docs separate them well. There is no client-facing results sheet: FR-14's per-run metrics report is Phase 6, not built. Several screen items blur the line (see Honesty issues) |

## Demo-breaking risks

Ranked by likelihood times impact.

1. **The operator dashboard exists only on this laptop.** `origin` has `main` and `phase-5-dashboard`. The 13 commits of `phase-5-operator-dashboard` (the whole operator page in `static/app/`) are not pushed. A fresh clone of GitHub `main` serves only the reference page. One disk failure loses it. `data/`, `models/` and the basemap are also not in git.
2. **S3 with Recorded media ticked alerts on birds** (4 to 10 alerts per run, `memory.md` Known issues). In front of a client whose brief says "tell drones from birds", this is the worst thing that could appear. Run S3 simulator-only.
3. **A run cannot be stopped or restarted.** The only controls are `pause`, `play` and `speed` (`contract.py:344`), and a second start returns 409 until the run ends. S1, S2, S4 and S5 last 120 s and S3 90 s. If a run goes wrong, use 5× or restart the server.
4. **Recorded-media runs stall the server and run near the real-time limit.** Models load inside the event loop (`scripts/live_runs.py:137`, marked `ponytail:`), so the page freezes for a few seconds after Start. Recorded-media S3 finished in 91.7 to 94.6 s against 97.2 s allowed (`memory.md`). The laptop has 7.7 GB of RAM, and earlier test runs were killed at about 88% memory. Screen-sharing or a video call during the demo can push it behind real time. 5× with recorded media will not keep up.
5. **The demo machine must be this laptop.** On another machine: no `data/` or `models/` (recorded media gives `404 recorded media is not ready`), no basemap (grid only), and on Linux the media manifest hash changes with line endings, so the weights are refused (`memory.md`, no `.gitattributes`). Downloading data needs internet and hours of training.
6. **Things that look wrong live:**
   - S1 shows only picket wedges for the first minute. Tracks confirm at 65.6 to 74.4 s, so start S1 at 2× or 5×.
   - S3 draws 26 tracks for 13 birds and a drone, with ghost and duplicate bird tracks and a p95 position error of 100 m.
   - At the full 7.2 km view, labels overlap near the site; use Close-up.
   - At 1366×768 the selected-alert panel scrolls, and the video overlay covers east-pointing wedges.
   - S2 picks its target up again under a new ID on 2 of 22 seeds. The default seed 2002 does not.
   - S5's fog shows a 21.9% coverage banner, and S5 has no video.
7. **Buttons can stick on "Saving…".** If the server is unreachable, `fetch` throws and `act()` never resets the button (`static/app/app.js:70-77`, `232-238`).
8. **Audio checked as playing but never heard**: headless Chrome is muted (`memory.md`). Test the speakers before the meeting.
9. **No internet needed and no GPU needed**: verified. No CDN or font loads in `static/`, the API docs pages are off, and torch is the CPU build. Hard-coded paths: none (paths come from `Path(__file__)`). Random results: none (seeded; identical digests across runs). Startup: about 1 s simulator-only; recorded media adds model loading (`memory.md` measured 3.6 s).

## Honesty issues

The project is careful overall. Exact text that can still mislead a client:

1. **Stand-in video is captioned as if it were the track's camera.** `static/app/text.js`: `clipAt: "{source} at {at} s"` renders as, for example, `st1.rgb at 12.3 s` over a stadium alert. The clip is a public Swedish dataset recording (an F450 or Phantom) chosen by simulated range (`sim/media.py`). The only nearby disclaimer is the map notice. The audio already has the right kind of caption (`audioNote: "Clean source audio. The classifier heard it mixed …"`), but the video has none.
2. **"Zoom" footage is not zoom footage.** `text.js`: `lookKind: { rgb: "RGB", thermal: "Thermal", zoom: "Zoom" }`. Per `memory.md` (Mocks), a zoom look is "a real RGB look on a held-out clip chosen as if the target were 4× closer, not a crop of the wide camera's frame".
3. **Health ticks that cannot fail.** `text.js`: `picketsOk: "{n} of {n} ✓ · visibility {vis}"`, `sensorOk: "✓"`, `noFaults: "Sensor faults: none"`. They come from `sim/station.py:181` and `sim/picket.py:187` (`# MOCK: simulated sensors never fail.`). They look like live health monitoring, which the brief asks for.
4. **Unqualified confidence percentages.** `app.js:124` renders `` `${class} ${Math.round(100 * a.confidence)}%` `` (for example "Drone 92%"). In simulator-only runs this number is fused from simulated movement and picket clues, with no model output. Only the map-corner notice says the scenario is simulated.
5. **Hand-off package says mock, not simulated.** `evidence/handoff.py:16`: `MOCK_NOTE = "Mock hand-off: a JSON file only, never sent. Detect and report only."` A package carries `p_drone`, positions and reasons, but no field says they came from a simulator run. Only `run_id` (for example `s2_seed2002_044`) hints at it.
6. **"Real AI on real recordings" needs its range caveat.** `prd.md` §2 and `README.md` ("Recorded-media mode runs the detectors and classifier on public RGB, thermal and audio recordings") are true. But the held-out figures (RGB 17 of 17 drone clips confirmed, thermal 24 of 24) come from 3 and 6 scene groups at short range, and the audio classifier (0.750) does not beat always answering `engine` (0.773). Any slide quoting these must carry those caveats. `memory.md` has them; a slide would not.
7. **The demo targets are not met and must not be presented as met.** `prd.md` §8: "Time to alert … ≤ 5 s" is missed (simulator-only S2 43.8 s and S3 49.8 s after track start in my runs; worst 65.0 s in `memory.md`). Recorded-media S2 gave 5.0 s after track start, but that is not the PRD's start event, so do not quote it as meeting the target. The doc itself says so, which is correct.

No invented number was found: every figure I checked in `memory.md` traces to a named script or run, and the evaluator prints `simulator results, not real-world performance`.

## Safety

- **No actuation code.** A search of `src/` for intercept, jam, takeover, mitigat, authoris, abort, override, serial, MAVLink and `socket` found nothing beyond the dashboard's own WebSocket. The only outgoing network code is in `scripts/download_data.py` and `scripts/fetch_basemap.py` (dataset and OpenStreetMap downloads). There is no `subprocess`, `os.system`, `eval` or `exec` in `src/` or `scripts/`.
- **The hand-off is a file only.** `evidence/handoff.py` writes JSON with `"mock": true`, and nothing sends it.
- **The server is local only**: `host: 127.0.0.1` in `site.yaml`, with no `--host` flag.
- **Human authorisation and abort flow: not present.** Nothing exists to authorise or abort, because no response or interception exists. The operator's Confirm and Dismiss only add evidence records; they change no system behaviour. This is consistent with `rules.md` §7. The brief's "interception only after human authorisation, with override and emergency abort" should be presented as a design for a separate, client-owned, authorised system, not as part of this demo.

## Security

- **Secrets, keys, `.env`:** none. I scanned all 115 commits on every branch for key, token, password, private-key, AWS, GitHub, OpenAI and Hugging Face patterns. The only hits were test fixtures named `secret.json` and `secret.txt` used for path-traversal tests. No `.env` file was ever committed.
- **Data, weights and runs:** never committed. In all history, the only path under `data/` is `data/README.md`; no `.pt`, `.pth`, `.mp4`, `.wav` or `runs/` path appears. The only file ever deleted is `config/scenarios/.gitkeep`.
- **Client data and real site coordinates:** none. There is no Saudi site, client footage or Haris material. The only real coordinates are the display anchor `anchor_lat: 50.78497` / `anchor_lon: -1.09457` (Southsea Common, Portsmouth, UK, a public park) in `config/site.yaml:165-166`.
- **Personal data in history:** 113 of 115 commits carry the author's personal Gmail address as the commit email (two use the GitHub noreply address). The repo is private, but anyone given access, the client included, will see it. Consider the noreply address for future commits.
- **Dashboard:** no authentication (local only, by design). Path traversal on `/api/clips` and the static mount is refused (tested). There is no Origin check on `/ws` (`server.py:357`), so any web page open in the same browser could read the stream. This is low risk on a local demo, but it would matter if the host were ever opened up.
- **Unsafe load:** `scripts/train_detector.py:65` calls `torch.load(self.path, map_location=CPU)` without `weights_only=True` on checkpoints that may come from Colab. The runtime loaders (`station/detector.py:68,75`, `station/sound.py:61`) use `weights_only=True`.

## Licences

**AGPL: none.** There is no Ultralytics or YOLO in `uv.lock`; the detector is torchvision's SSDLite (BSD-3-Clause).

Runtime dependencies (installed versions, licences from package metadata):

| Package | Licence | Flag |
| --- | --- | --- |
| av 18.1.0 (PyAV) | BSD-3-Clause; the wheel bundles FFmpeg (LGPL) **and `libx264`, `libx265` (GPL-2.0+)**, plus opencore-amr | **Flag**: GPL codecs in the shipped wheel. Decode-only use, but check before redistributing |
| torch 2.15.0+cpu | BSD-3-Clause style (Apache-2.0, BSD, MIT, Zlib, BSL components) | |
| torchvision 0.29.2+cpu | BSD-3-Clause | |
| numpy 2.4.6 | BSD-3-Clause (+0BSD, MIT, Zlib, CC0) | |
| scipy 1.17.1 | BSD-3-Clause | |
| pydantic 2.14.3, pydantic-core 2.50.4 | MIT | |
| fastapi 0.162.2 | MIT | |
| starlette 1.10.0 | BSD-3-Clause | |
| uvicorn 0.54.0, websockets 17.4, click 8.5.1, idna 3.20 | BSD-3-Clause | |
| PyYAML 6.0.3, anyio 4.16.0, h11 0.16.0, annotated-doc, annotated-types, typing-inspection | MIT | |
| opentelemetry-api 1.45.2 | Apache-2.0 | |
| typing-extensions 4.16.0 | PSF-2.0 | |
| pillow 13.0.0 | MIT-CMU | |
| torch's own: sympy, mpmath, networkx, jinja2, markupsafe, filelock, fsspec, setuptools | BSD or MIT | |
| colorama 0.4.6 | BSD | |

Development only: httpx and httpcore (BSD-3-Clause), **certifi (MPL-2.0, weak copyleft, test only)**, pytest, pluggy, iniconfig and ruff (MIT), pytest-asyncio (Apache-2.0), Pygments (BSD-2-Clause), packaging (Apache-2.0 or BSD-2-Clause).

Model weights and datasets:

| Item | Licence | Flag |
| --- | --- | --- |
| SSDLite320 MobileNetV3 COCO starting weights (`models/pretrained/`) | Code BSD-3-Clause; **weights have no stated licence**; COCO images are under Flickr terms | **Unknown**: counsel review |
| `models/look_rgb.pt`, `look_thermal.pt` (our fine-tunes) | Derived from the above plus Svanström | **Unknown**: inherit both |
| `models/sound.pt` | Trained on Svanström audio plus FSD50K CC0 clips | Inherits Svanström's mismatch |
| Svanström Drone Detection Dataset | CC0-1.0 in the repo, "Other (Open)" on Zenodo, CC BY 4.0 on the article | **Unknown**: the sources disagree. 49 YouTube clips and all helicopter audio excluded |
| FSD50K (`Engine` clips, CC0 only) | Dataset CC BY; per-clip licences; "commercial use requires contacting the authors" | **Flag**: commercial use not cleared |
| OpenStreetMap basemap (Portsmouth) | ODbL 1.0, attribution required (shown) | Share-alike if the derived file is distributed |
| Ruled out: Drone Audio Dataset; Drone-vs-Bird | Non-commercial, bars defence and surveillance use; research only under agreement | Correctly not used |

All of this is recorded in `data/README.md`, with a "Before client delivery" to-do list that is still open.

## Top 10 code issues

1. **Operator requests can hang forever.** `src/cuas/dashboard/server.py:206-218`: `_ask` awaits the keeper's answer with no timeout. In `src/cuas/evidence/keeper.py:242-248`, if `keeper.handle` raises (for example an `OSError` writing a snapshot), the `answer()` task dies silently. Every later Confirm, Dismiss or Export then hangs until the run ends, and the button shows "Saving…".
2. **Front end has no network-error handling.** `src/cuas/dashboard/static/app/app.js:70-77`: `post()` catches a bad JSON body but not a rejected `fetch`. `act()` (`app.js:229-245`) then never resets the button, and `startRun()` (`app.js:79-83`) fails silently.
3. **A run cannot be stopped.** `src/cuas/dashboard/contract.py:343-345` allows only `pause`, `play` and `speed`, and `Hub` has no stop. There is no way to abandon a bad run except restarting the process.
4. **A failed run looks like a finished run.** `server.py:275-281`: `_end_when_done` logs the exception and publishes `state: "ended"`, which is the same as a normal end. The operator is never told the run crashed.
5. **Model loading blocks the event loop.** `scripts/live_runs.py:137-150` (marked `ponytail:`) builds the media link synchronously inside the request handler, which freezes every WebSocket client for seconds.
6. **The audit trail has no wall-clock time and no operator.** `src/cuas/schemas/evidence_record.py:18-35`: records have `t` (simulated seconds) and `request_id` only. A real audit trail needs who and when. Adding fields changes the chain format, so it needs a contract decision.
7. **Health monitoring cannot be exercised.** `src/cuas/sim/station.py:181` and `src/cuas/sim/picket.py:187` hard-code `ok=True`. No scenario injects a fault, so the dashboard's fault path is tested only against the hand-made `docs/samples/edge_states.jsonl`.
8. **About 840 lines of operator JS have no automated tests.** `static/app/app.js` (469 lines) and `map.js` (374) are checked only by a headless-Chrome script kept outside the repo (`memory.md`). Issues 2 and 7 above are the kind such tests would catch.
9. **The clock advances before honouring a pause.** `src/cuas/clock.py:76-78`: `tick()` increments `_ticks` before `await self._running.wait()`. While paused, `clock.now` is one tick (0.2 s) ahead of the last published observations, and labels made while paused (`server.py:171`) are stamped with that future time.
10. **Assertions and checkpoint loading.** `server.py:186` and `server.py:210` use `assert` for runtime state checks, which are removed under `python -O`. `scripts/train_detector.py:65` loads checkpoints without `weights_only=True`. Also still open: the line-ending-dependent manifest hash (no `.gitattributes`; planned for Phase 6), which breaks a fresh Linux clone.

## Fix before Monday

Ranked by value to the demo. Under `docs/rules.md` §1, any code change needs a short plan and your approval, and Phase 5 is still awaiting acceptance. Items 1 to 5 are not code.

| # | Fix | Effort |
| --- | --- | --- |
| 1 | Back up the demo: push `phase-5-operator-dashboard` to the private remote, or at least copy the repo with `data/`, `models/` and `data/basemap/` to a second drive. Rehearse on the demo laptop itself, with the network off and the speakers on | S |
| 2 | Write a one-page client sheet: "Measured on public recordings" (with scene counts and range caveats), "Simulator only" and "Not in this demo" (15 km / 10 km ranges, interceptor, recommendations, authorisation, abort). Answer the brief's gaps before the client finds them | S |
| 3 | Demo runbook: S2 (Recorded media on) → S5 → S1 at 2× or 5× → S4 → S3 **simulator-only**; Close-up on; close other apps; restart the server between runs if needed; never 5× with recorded media | S |
| 4 | Decide the story for "recommendations, human authorisation, abort". Recommended: present it as an architecture slide for the client's own authorised response system, and keep this repo detect-and-report only. Building even a mock in this repo would break `rules.md` §7 and need your explicit decision | S (slide) / L (any code) |
| 5 | Remove the commit email from future commits (noreply address) before giving the client repo access | S |
| 6 | Caption the video honestly: for example "Public dataset clip (Svanström, Sweden), chosen by simulated range; not footage of this target". Rename the "Zoom" tab to something like "Zoom (stand-in clip)" (`text.js`) | S |
| 7 | Label simulated health and confidence on screen: "✓ (simulated)" on sensors and pickets, and "(simulated)" beside class % when `recorded_media` is false (`text.js`, `app.js:124`) | S |
| 8 | Catch `fetch` errors in `post()` and always reset the button in `act()` (`app.js:70-77`, `229-245`) | S |
| 9 | Add a timeout to `Hub._ask`, and keep the keeper's `answer()` loop alive on an exception (`server.py:206-218`, `keeper.py:242-248`) | S |
| 10 | Show "Run failed, see the console" when a run ends with an exception (`server.py:275-281`, plus one UI string) | S |
| 11 | Add a Stop action to `RunControl` and `Hub`: contract change, UI button, tests | M |
| 12 | Load models in a thread (`asyncio.to_thread`) in `live_runs.py:137` | S to M (needs a real-time recheck) |
| 13 | Wall-clock time and operator ID in evidence records | M to L (chain format and contract change; not before Monday) |
| 14 | Add `.gitattributes` for the media manifest (planned Phase 6 work) | S |

Items 6 to 10 together are about half a day with tests and a dashboard re-check. Items 11 to 14 are better left until after Monday.
