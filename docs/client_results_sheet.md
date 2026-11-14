# Results sheet: what each number in the demo is

Every number shown or quoted in the demo, labelled:

- **MEASURED on public dataset clips:** produced by our evaluation script on held-out recordings from public datasets. It shows how the models behave on those clips, **not field performance**.
- **SIMULATED:** produced by the scenario simulator. The sites, targets, sensors and their errors are simulated. It shows the software chain works; it says nothing about real-world detection.
- **PROJECTED:** from literature or calculation. **None is shown in this demo build.**

Sources: `docs/memory.md` (Measured results), `REVIEW.md`, and the evaluator output of `scripts/run_demo.py --scenario <id> --fast` on each scenario's own seed, run on 2026-11-14. No number here was produced for this sheet alone.

## On screen during a run

| What the screen shows | Label | Where it comes from |
| --- | --- | --- |
| Confidence on a card ("Drone 99%"), tagged SIM | SIMULATED | Fusion of movement, sound and look clues on simulated tracks. With Recorded media, the look clue is real model output on a public clip. Shown capped at 99% |
| "camera look 64% drone" in a card's reasons | MEASURED on public dataset clips | The real detector's output on a held-out public clip chosen to match the simulated distance. Not a measurement of the simulated target |
| Time to impact (TTI), INSIDE ZONE | SIMULATED | Fitted to simulated track positions |
| Position, altitude, ground speed, direction of travel | SIMULATED | Triangulated from simulated bearings |
| Coverage % (S2 100%, S4 54.8%, S5 21.9%) | SIMULATED | Coverage grid over simulated sensor ranges and visibility |
| Sensor health ✓ and visibility factors, tagged SIM | SIMULATED | Simulated sensors never report a fault (a mock) |
| Picket wedges "Engine heard …" | SIMULATED | Simulated pickets. With Recorded media the engine guess comes from the real audio model on a public clip |
| Evidence record count, SHA-256 hashes, `cuas verify` | Computed for real | Real SHA-256 over the files this run wrote |
| Clock (mm:ss.s) | SIMULATED | Simulated time |
| SIMULATED camera view in S1 (dot, crosshair, range in km, "Camera detection at 00:38.6 by st2") | SIMULATED | Drawn by the dashboard from the simulated camera bearing or the estimated track; no footage. The dot is sized for a 2.5 m drone (client brief), not measured |

## Detection and classification on public clips (MEASURED on public dataset clips)

From `scripts/evaluate_media.py` on the held-out test split (`runs/eval/`). Data: Svanström Drone Detection Dataset (video and drone audio, recorded in Sweden) and FSD50K `Engine` clips (mostly road vehicles, used as an engine proxy). 95% intervals in brackets.

| Model | Result |
| --- | --- |
| RGB detector | Drone clips confirmed 17 of 17 (0.816 to 1.000). Other clips with a false drone track 7 of 19 (0.191 to 0.590). Median 1.2 s to confirm. Frame precision 0.805, recall 0.837. Drone miss rate: close 0.283, medium 0.159, distant 0.085. 82.5 ms per frame on 4 CPU threads |
| Thermal detector | Drone clips confirmed 24 of 24 (0.862 to 1.000). Other clips with a false drone track 6 of 31 (0.092 to 0.363). Median 1.2 s to confirm. Frame precision 0.792, recall 0.897. Airplane precision 0.307, recall 0.205. 90.3 ms per frame on 4 CPU threads |
| Audio classifier | Accuracy 0.750 on clean clips (0.606 to 0.854), against 0.773 for always answering "engine". With added noise at +20, +10, 0 and −10 dB: 0.750, 0.636, 0.523, 0.273. 4.1 ms per 1 s window |

Limits that must go with these numbers:
- Few scenes: RGB's 17 drone clips come from 3 scene groups and thermal's 24 from 6, so the intervals are too narrow.
- Short range: the dataset's "distant" class starts at 60 m and gives no exact distances. Nothing here measures detection at kilometres.
- The audio model does not beat its baseline, and the engine class is not attack-drone audio.
- Empty-sky false alarms were not measured: the test frames almost all contain a target.

## Bird false alerts with the real models (MEASURED on public dataset clips, in SIMULATED scenes)

From `scripts/compare_zoom.py` (commit `98b14e1`): scenario S3 with Recorded media, seeds 3003 and 1 to 4, simulated geometry with real model output on held-out public clips.

| Zoom cameras per station | False alerts on birds or false tracks, summed over 5 runs |
| --- | --- |
| 0 | 37 |
| 1 (the demo default) | 24 |
| 2 | 21 |

Per run without zoom: 4 to 10 false alerts. Zoom reduced them but never removed them, and not on every seed (seed 4 got worse with one camera). On the simulator alone, S3 raises no bird alerts. **This is why the demo shows S3 on the simulator only.** No fix has been made since; the cause (detectors giving some bird clips drone looks) is listed in `docs/known_issues.md`.

## Scenario results (SIMULATED)

From the evaluator lines of `run_demo.py --scenario <id> --fast`, own seed, 2026-11-14, simulator only.

| Scenario | Result |
| --- | --- |
| S1, 3 attack drones | 3 confirmed tracks, 0 false. Median position error 0.97 m, p95 6.15 m. Picket warning 73.8 to 85.8 s before arrival. Tracks confirmed 1,630 to 1,780 m from the site centre. Red 3.6 to 15.6 s after each track started |
| S2, 1 quadcopter | 1 track. Median position error 0.36 m, p95 1.35 m. Red 43.8 s after its track started (5.0 s with Recorded media) |
| S3, 12 birds and 1 quadcopter | 0 amber or red alerts on birds. 26 confirmed tracks for 13 targets, 4 of them false, with duplicates; p95 position error 100.23 m. The quadcopter red 49.8 s after its track started |
| S4, S2 in dust | Coverage 54.8%, warning shown. Red 14.2 s after the track started |
| S5, acoustic-first in fog | Coverage 21.9%. A station microphone warned 5.2 s before any camera bearing (seed 5005; 1.6 to 6.0 s on seeds 1 to 5). The fog was chosen to give cameras less range than microphones: a demonstration, not a performance claim |

Over many seeds (`docs/memory.md`): exactly 3 confirmed S1 tracks on all 22 seeds tested; no bird or ghost alerts on the development seeds.

Our own demo target of red within 5 s of the first two-station detection (`docs/prd.md`) is **missed** in the simulator (worst 65.0 s on the development seeds).

## Simulator settings that look like performance but are not

These are start values in `config/site.yaml`, chosen by us, not measured:

| Setting | Value |
| --- | --- |
| Camera range, attack drone | 3,000 m (RGB and thermal) |
| Camera range, quadcopter | 800 m RGB, 600 m thermal |
| Station microphone range | 1,500 m attack drone, 300 m quadcopter |
| Picket ring and hearing radius | 3 km ring; 1,500 m for a piston engine |
| Station spacing | 500 m |

## PROJECTED

None in this build. The client brief asks for detection at 15 km and classification at about 10 km. No screen in this demo shows such a figure, and no test supports it. Any long-range figure discussed comes from our literature review and must be presented as a projection with its source.
