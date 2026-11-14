# Demo run order: Haris Unmanned Systems, Monday 2026-11-16

A 5 to 7 minute walkthrough: **S2** (small drone) → **S1** (attack-drone wave) → **S3 on the simulator only** (birds rejected) → **evidence check and hand-off export**. Times below are simulated time on the dashboard clock, measured on this laptop on 2026-11-14 with each scenario's own seed. They are simulator results, not field performance.

Two rules:
- **Never run S3 with Recorded media ticked.** With the real models on public clips it raises false alerts on birds (4 to 10 per run; `docs/client_results_sheet.md`).
- **Use the ■ Stop button between runs.** Do not restart the server. Stop ends the run cleanly, keeps its evidence and frees the dashboard for the next run.

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

## 1. S2: one small drone over a stadium (about 2 minutes)

**Clicks:** Site profile **Fictional Stadium** → Scenario **S2: Stadium watch** → tick **Recorded media** → **Start monitoring** → **2×**.

Use 2×, not 5×: the first recorded-media run fell up to 1.4 s behind real time at 2× on this laptop and caught up; nothing on screen warns of lag yet.

| Clock | What appears | What to say |
| --- | --- | --- |
| 00:12 | The track is confirmed from three stations | "Three camera masts each report only a bearing. The tracker crosses the bearings into a 3D position." |
| 00:16 | **RED** card: Drone with confidence, TTI, reasons. **Pause.** Click the card | "The operator gets a ranked alert with the reasons behind it. The SIM tag means the number comes from the simulator, not a real sensor." |
| (paused) | Video over the map: caption "Sample clip from Svanström Drone Detection Dataset - not footage of this track". Try the **Zoom (stand-in clip)** tab | "The detector is real. It runs on public recordings chosen to match the simulated distance. This is not footage of this drone." |
| (paused) | **Confirm**, then **Export hand-off JSON**: the card shows the file path and its SHA-256 | "Every action is written to a tamper-evident evidence chain. The hand-off is a JSON file only; nothing is sent anywhere." |
| 00:39 | **Play.** Under Evidence, **Sample recording from Svanström Drone Detection Dataset** | "The microphone clue: clean source audio. The classifier heard it mixed with noise for the simulated distance and wind." |
| 01:05 | **INSIDE ZONE** flashes on the card (Pitch and Stands) | "The drone is now over the pitch: the most urgent state." |

Then **■ Stop** → **Stop run**. Note the run folder shown under System status (for example `runs/s2_seed2002_047`).

Export and Confirm work only while the run is live: do them before Stop.

## 2. S1: wave of three attack drones (about 1.5 minutes)

**Clicks:** Site profile **Fictional Processing Plant** → **S1: Processing plant watch** → leave **Recorded media unticked** → **Start monitoring** → **5×**. Tick **Close-up** once tracks appear.

| Clock | What appears | What to say |
| --- | --- | --- |
| 00:19 | Amber wedges at the outer pickets: "pk… · Engine heard … · Unconfirmed" | "Acoustic pickets 3 km out hear engines long before any camera. They give a direction only, so we show a wedge, not a dot." |
| 01:06 | Tracks confirmed as the drones come within camera range | "When cameras on two masts see a drone, it gets a position and a track." |
| 01:16 | Three **RED** cards ranked by time to impact | "Several targets at once, ranked by which one arrives first." |
| 01:38 | **INSIDE ZONE** on the first card | |

**■ Stop** when the point is made, or let it end (2 minutes simulated, about 24 s at 5×).

S1 has no video: the public datasets contain no fixed-wing drone footage. Say so if asked.

## 3. S3 on the simulator only: birds and one drone (about 1 minute)

**Clicks:** Fictional Stadium → **S3: Stadium watch, second period** → **Recorded media unticked** (check it) → **Start monitoring** → **5×**.

| Clock | What appears | What to say |
| --- | --- | --- |
| from 00:02 | Up to 14 tracks at once, most of them birds, all without alerts | "Birds are tracked like anything else, but their movement doesn't look like a drone's, so they never raise an alert." |
| 01:08 | One **RED** card: the quadcopter, already over the pitch | "Only the drone is alerted." |

Be ready for "some bird tracks are duplicated": that is true in the simulator (13 targets give 26 confirmed tracks over the run), and none of them alerts.

**■ Stop.**

## 4. Evidence and hand-off (about 1 minute)

In the second terminal, with the S2 run folder from step 1:

```
uv run cuas verify runs/s2_seed2002_047
```

It prints `verified … records, … files, head seq …`. Open the hand-off file listed on the S2 card (`runs/<folder>/handoff/…json`) to show the package: alert, track history, operator label, clip hashes, `"mock": true`.

"Each record carries the hash of the one before it. Change one byte in the evidence folder and `verify` fails."

## Backup plan

| Problem | Do this |
| --- | --- |
| Page looks frozen or blank | Reload the page (F5). It reconnects and redraws the current run |
| A run misbehaves | **■ Stop** → **Stop run**, then start it again |
| "Recorded media unavailable: …" | Run S2 without Recorded media: the tracking and alerts are the same, with no video or audio |
| The server window shows an error, or the page cannot connect | Ctrl+C in the server window, start it again (models ready in about 4 s), reload the page |
| Run title says "failed: see the server console" | Stop showing that scenario; continue with the next |
| Nothing works | Replay a recorded stream: `uv run python scripts/run_demo.py --dashboard --replay docs/samples/s1_seed1001.jsonl` (no evidence, no video) |

## Honest answers to likely questions

- **"Can it detect at 15 km and classify at 10 km?"** Not in this demo. The simulator uses start values of up to 3 km for cameras and 1.5 km for microphones, and the real-model results come from public clips at short range (the dataset's "distant" class starts at 60 m). Long-range figures come from our literature review and are projections, not measurements.
- **"Where is the interceptor? Who authorises it?"** Planned, not built. This build detects and reports only. The design keeps any response behind explicit human authorisation, with override and abort. Today the hand-off is a mock JSON file.
- **"What about small drones far away?"** Unproven at range. The quadcopter's simulated camera range is 800 m, and the public clips do not give exact distances.
- **"Will the microphones work in the desert?"** Untested. The audio model was trained on Swedish recordings and road-vehicle sounds, and it does not yet beat a simple baseline (0.750 against 0.773). Wind and heat are not in the data.
- **"Is this your footage?"** No. All video and audio come from public datasets (Svanström Drone Detection Dataset, FSD50K), as the captions say. No client or site footage is used.
- **"Birds?"** On the simulator, no bird alerts. With the real models on public clips, birds still caused 4 to 10 false alerts per run (5 runs); that is the next fix.
- **"Aircraft?"** Not in these scenarios. The detector has airplane and helicopter classes, but they are not used to suppress alerts yet.
- **"How fast is an alert?"** Our own target is red within 5 s of the first two-station detection. We miss it in the simulator: for example S2 turns red 43.8 s after its track starts without recorded media.
