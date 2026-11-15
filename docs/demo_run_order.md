# Demo run order: Haris Unmanned Systems, Monday 2026-11-16

A 5 minute walkthrough of **two scenarios**: **S1** (attack-drone wave, the default) → **S2** (small drone) → **evidence check and hand-off export**. The Scenario dropdown lists only these two (`dashboard.demo_scenarios` in `config/site.yaml`); S3 to S5 still exist but are hidden. Times below are simulated time on the dashboard clock, measured on this laptop with each scenario's own seed. They are simulator results, not field performance.

Two rules:
- **Use the ■ Stop button between runs.** Do not restart the server. Stop ends the run cleanly, keeps its evidence and frees the dashboard for the next run.
- **Picking a scenario picks its site**: the Site profile follows the Scenario dropdown by itself.

At natural run end, the queue becomes **Run complete**, with the scenario, simulation duration,
last recorded detection, historical position and separate track/evidence counts. **Export run
summary** saves local JSON. Stop displays **Run stopped**. Starting another run clears it.
See `run_summary_verification.md` for measured simulator-only summaries and rehearsal steps.

## Before the meeting (10 minutes)

1. Use this laptop: the recordings and models are only here (and in the private backup zip). Plug in the charger.
2. Close everything else: video calls, browsers with many tabs, OneDrive sync, Teams. Turn on Windows "Do not disturb". The laptop has 7.7 GB of RAM.
3. Open a terminal in `cuas-demo/` and start the server:
   `uv run python scripts/run_demo.py --dashboard`
   Leave this window open. It prints the dashboard address and, after each run, the run folder.
4. Open http://127.0.0.1:8000/ in Chrome. Wait until the top bar says **"AI models ready"** (about 4 seconds after the server starts). **Start monitoring** stays disabled until then. If it says "Recorded media unavailable: …", see the backup plan.
5. Browser zoom 100% at 1920×1080, or 90% at 1366×768 (Ctrl and minus). Press F11 for full screen.
6. Test the speakers: the S2 recorded audio is played from the dashboard.
7. Open a second terminal in `cuas-demo/` for the evidence check at the end.
8. No warm-up run: the models load and warm up when the server starts.

The dashboard needs no internet. Wi-Fi can be off.

After editing dashboard Python code, restart the server once the current run has ended, then
hard-refresh Chrome. The page can otherwise serve newer JavaScript against older in-memory
API handlers. A summary HTTP 404 says to restart and start a fresh run; see
`run_summary_failure.md` for the reproduced case and captured responses.

## 1. S1: large attack drones, processing plant (about 2 minutes)

**Clicks:** Scenario **S1: Large attack drone - processing plant** (already selected) → leave **Recorded media unticked** → **Start monitoring** → **2×** until 01:10, then **5×**. **Do not click a card before 01:16**: with nothing selected, the video panel follows the highest-priority detection by itself. Tick **Close-up** once tracks appear.

**S1 camera handoff:** acoustic warning, then wide-camera detection text, then Zoom once the target enters its simulated field of view. After that, a fresh RGB bearing uniquely linked to the same track permits automatic Wide RGB fallback. Status: "Wide RGB · Zoom repositioning" while Zoom remains assigned. Reacquisition returns to Zoom without changing the selected alert. With neither camera seeing it: "Target out of camera view"; the estimated map track follows its normal lifetime. Wide RGB reuses the local distant-approach DVIDS cut as an illustration: STAND-IN, DVIDS / Tech. Sgt. Michael McGhee, public domain, not footage of this track. Missing asset: "No Wide RGB clip available." S2 retains its existing Zoom/sample playback.

| Clock | What appears | What to say |
| --- | --- | --- |
| 00:19 | Amber wedges at the outer pickets: "pk4 · Engine heard … · Unconfirmed" | "Acoustic pickets 3 km out hear a piston engine long before any camera. A picket gives a direction only, so we show a wedge, not a dot." |
| 00:23 | **Step 1.** The video panel opens by itself with no picture: "Acoustic detection only - camera cued to bearing 137°, searching" | "The system points the nearest camera at the picket that heard it. Nothing is seen yet, so we say so: there is no picture to show." |
| 00:39 | **Step 2.** Still text only: "Wide camera detection at 00:38.6 by st2 - zoom slewing to target". The evidence head under System status moves to record 1 | "A wide camera has found it, about 20 degrees from where the picket pointed us. One camera gives a direction but no range. The detection is written to the evidence chain at that moment, and the zoom camera is being turned onto it." |
| 01:06 | **Step 3.** The **ZOOM camera (stand-in clip)** tab appears and the video starts: "Zoom camera st3 on the target" | "A second mast also sees it, so it has a position and a range, and the zoom camera is on it. The video is a stand-in: real footage of a similar fixed-wing drone, not this one, and the screen says so." |
| 01:16 | Three **RED** cards ranked by time to impact. Cards whose camera view is not on screen carry a yellow **Camera detected** badge | "Several targets at once, ranked by which one arrives first. The panel follows the top one; the badge says the others have been seen by a camera too." |
| after 01:16 | Click any card: the panel follows that drone: its text, or its zoom video once a zoom camera is on it | "The operator chooses what to look at; the system never takes the panel away from a chosen alert." |
| 01:38 | **INSIDE ZONE** on the first card | |
| around 01:25 | Zoom and Wide RGB hand off as the target crosses the Zoom field boundary | "Wide RGB still sees this track while Zoom repositions. Both videos are illustrative." |

**■ Stop** when the point is made, or let it end (2 minutes simulated).

If asked "is that a real camera?": no. The clips are real footage, but of another aircraft on another day: a US Army RQ-7B Shadow at a 2016 flight demonstration in Iowa, published by DVIDS as public domain. When the panel shows video, and which zoom camera is named, follows this track's simulated zoom assignment; the picture does not. No detector ran on these clips and no box is drawn on them. Their use implies no endorsement by the US Department of Defense. The public drone datasets contain no fixed-wing drone footage, which is why a stand-in is used.

## 2. S2: one small drone over a stadium (about 2 minutes)

**Clicks:** Scenario **S2: Small drone - stadium** → tick **Recorded media** → **Start monitoring** → **2×**.

Use 2×, not 5×: the first recorded-media run fell up to 1.4 s behind real time at 2× on this laptop and caught up; nothing on screen warns of lag yet.

S2 opens Zoom sample video automatically for the highest-ranked alert with an assigned Zoom camera; manual selection takes priority. When a linked microphone bearing arrives, that same track gets the dashed yellow Last heard from wedge with station and timestamp. Acoustic sectors hides both this wedge and the separate solid amber unconfirmed sectors. The local held-out sample sequence is V_DRONE_027, the existing clear portions of V_DRONE_033 and V_DRONE_032, then the visibly different blue-sky V_DRONE_102. Source duration: 31.4 s, about 29.6 s with crossfades. It plays once, holds its last frame and displays Sample clip ended with Replay. SAMPLE and the Svanström source caption stay visible. Routine updates do not restart it. See s2_dashboard_verification.md for the rehearsal and browser verification limits.

| Clock | What appears | What to say |
| --- | --- | --- |
| 00:12 | The track is confirmed from three stations | "Three camera masts each report only a bearing. The tracker crosses the bearings into a 3D position." |
| 00:16 | **RED** card: Drone with confidence, TTI, reasons. The panel opens by itself with **ZOOM camera (sample clip)**. **Pause.** Click the card | "The operator gets a ranked alert with the reasons behind it. The SIM tag means the number comes from the simulator, not a real sensor." |
| (paused) | The zoom video over the map: "Zoom camera st1 on the target" | "The detector is real and runs on public recordings chosen to match the simulated distance. These are sample clips of a real drone from a public dataset; detector performance is measured separately on held-out clips - see the results sheet. This is not footage of this drone." |
| (paused) | **Confirm**, then **Export hand-off JSON**: the card shows the file path and its SHA-256 | "Every action is written to a tamper-evident evidence chain. The hand-off is a JSON file only; nothing is sent anywhere." |
| 00:39 | **Play.** Under Evidence, **Sample recording from Svanström Drone Detection Dataset** | "The microphone clue: clean source audio. The classifier heard it mixed with noise for the simulated distance and wind." |
| 01:05 | **INSIDE ZONE** flashes on the card (Pitch and Stands) | "The drone is now over the pitch: the most urgent state." |

Then **■ Stop** → **Stop run**. Note the run folder shown under System status (for example `runs/s2_seed2002_047`).

Export and Confirm work only while the run is live: do them before Stop.

## 3. Evidence and hand-off (about 1 minute)

In the second terminal, with the S2 run folder from step 2:

```
uv run cuas verify runs/s2_seed2002_047
```

It prints `verified … records, … files, head seq …`. Open the hand-off file listed on the S2 card (`runs/<folder>/handoff/…json`) to show the package: alert, track history, operator label, clip hashes, `"mock": true`.

"Each record carries the hash of the one before it. Change one byte in the evidence folder and `verify` fails."

## Backup plan

| Problem | Do this |
| --- | --- |
| Page looks frozen or blank, or shows old behaviour | Reload the page (F5). It reconnects and redraws the current run; every file is sent with `Cache-Control: no-cache`, so F5 always loads the current page code |
| A run misbehaves | **■ Stop** → **Stop run**, then start it again |
| "Recorded media unavailable: …" | Run S2 without Recorded media: the tracking and alerts are the same, with no video or audio |
| A camera tab reads "(simulated)" and shows a drawn view | That clip is missing or changed on this machine (`config/display_clips.yaml` records each hash); the simulated view is the fallback |
| The server window shows an error, or the page cannot connect | Ctrl+C in the server window, start it again (models ready in about 4 s), reload the page |
| The map shows a grid and "local grid 500 m (no basemap)" | Press F5. The page fetches the map once when it loads; if the server was not answering at that moment (for example the tab reopened before the server started), it keeps the grid until reloaded |
| Run title says "failed: see the server console" | Stop showing that scenario; continue with the next |
| Nothing works | Replay a recorded stream: `uv run python scripts/run_demo.py --dashboard --replay docs/samples/s1_seed1001.jsonl` (no evidence, no video) |

## Honest answers to likely questions

- **"Can it detect at 15 km and classify at 10 km?"** Not in this demo. The simulator uses start values of up to 3 km for cameras and 1.5 km for microphones, and the real-model results come from public clips at short range (the dataset's "distant" class starts at 60 m). Long-range figures come from our literature review and are projections, not measurements.
- **"Where is the interceptor? Who authorises it?"** Planned, not built. This build detects and reports only. The design keeps any response behind explicit human authorisation, with override and abort. Today the hand-off is a mock JSON file.
- **"What about small drones far away?"** Unproven at range. The quadcopter's simulated camera range is 800 m, and the public clips do not give exact distances.
- **"Will the microphones work in the desert?"** Untested. The audio model was trained on Swedish recordings and road-vehicle sounds, and it does not yet beat a simple baseline (0.750 against 0.773). Wind and heat are not in the data.
- **"Is this your footage?"** No. S2's video and all audio come from public datasets (Svanström Drone Detection Dataset, FSD50K); S1's video is public-domain DVIDS footage of an RQ-7B Shadow, used as a stand-in. The captions say which. No client or site footage is used.
- **"Birds?"** Not in today's two scenarios. On the simulator (S3, hidden today), no bird alerts. With the real models on public clips, birds still caused 4 to 10 false alerts per run (5 runs); that is the next fix.
- **"Aircraft?"** Not in these scenarios. The detector has airplane and helicopter classes, but they are not used to suppress alerts yet.
- **"How fast is an alert?"** Our own target is red within 5 s of the first two-station detection. We miss it in the simulator: for example S2 turns red 43.8 s after its track starts without recorded media.
