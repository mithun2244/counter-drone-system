# Counter Drone System

Passive counter-drone detection demo. The simulator generates the site geometry and sensor observations. Recorded-media mode runs the detectors and classifier on public RGB, thermal and audio recordings.

## Run the operator dashboard

From the repository root, with Python 3.11 and `uv` available:

```sh
uv sync
uv run python scripts/run_demo.py --dashboard
```

Open [the operator dashboard](http://127.0.0.1:8000/). It works offline and loads nothing from the internet.

1. The AI models load as the server starts; the top bar shows "Loading models… n of 4" and enables **Start monitoring** when they are ready (a model that cannot load is named there, and simulator runs still work). Select **Fictional Processing Plant**, choose **S1**, and click **Start monitoring**. Use **1× / 2× / 5×** and **Pause** to control the simulated clock, and **■ Stop**, then **Stop run**, to end a run early and start another; its evidence is kept.
2. Watch the map: pickets flash, and labelled amber wedges (for example "pk4 · Engine heard south-east · Unconfirmed") show engines heard but not yet placed. **Acoustic sectors** turns them on or off, and **Acoustic detections**, under System status, lists them. Tracks appear as dots with trails, labelled with their level. Tick **Bearing rays** to see the station bearings, and **Close-up** to fit the map to the site.
3. The **Alert queue** on the right lists alerts in the server's ranking, with time to impact counting down. **System status**, on the left, shows coverage, each station's sensors, faults and the evidence head.
4. Click a card. Its track gets a ring on the map, and **Selected alert** opens below the queue with the track's estimated position, altitude, ground speed, direction of travel, contributing stations and coasting state. Values that cannot be shown say why. With recorded media, a confirmed track that a station microphone was matched to also gets a dashed yellow **Last heard from** wedge, with the station, direction and time.
5. With **Recorded media** ticked before starting (Fictional Stadium, S2), the selected alert's video plays over the upper right of the map. Pick a camera with its tab, and collapse or expand it with **−** / **+**. Under **Evidence**, **Recorded audio** plays each station's clean source audio.
6. On a card, **Confirm** or **Dismiss** saves a label in the evidence chain, and **Export hand-off JSON** saves a mock hand-off package and shows its path and SHA-256 on the card and in the evidence section.
7. After the run, check its evidence with `uv run cuas verify runs/<run_id>`. The run folder is shown in **System status**.
8. S5 remains an optional acoustic-first replay, outside the two-scenario demo dropdown: `uv run python scripts/run_demo.py --dashboard --replay docs/samples/s5_seed5005.jsonl`. `uv run python scripts/acoustic_lead.py s5` prints its detection order. This is a simulator demonstration, not a performance claim.

The processed basemap `data/basemap/portsmouth.json` is committed, so a fresh clone draws the map offline; `scripts/fetch_basemap.py` rebuilds it, and without it the map draws a local grid. For recorded-media runs, prepare the local recordings and model weights as described in the [dashboard contract](docs/dashboard_contract.md) and [data source notes](data/README.md). The [reference page](http://127.0.0.1:8000/reference/) is a minimal independent check of the same contract. See [phase status and acceptance checks](docs/phases.md) for Phase 5 acceptance and the Phase 6 plan.

The current demo lists **S1 and S2**; S3–S5 remain available through the CLI or replay files.
S1 preserves acoustic warning → wide-camera detection text → Zoom acquisition, then switches
to Wide RGB when a fresh observation uniquely matches the same track and Zoom loses it.
Wide footage is explicitly **STAND-IN**, credited to DVIDS. S2 automatically shows the linked
yellow microphone wedge for the video subject, with manual selection taking priority. Acoustic
sectors controls both the yellow linked wedge and separate solid amber unconfirmed sectors.
Its four held-out **SAMPLE** cuts play once, hold the final frame and offer **Replay**; source
duration is 31.4 s, approximately 29.6 s after crossfades.

At run end, the queue becomes **Run complete** or **Run stopped**, with last detection details,
a historical estimate on the map, separate alerted-track/evidence counts and **Export run
summary** (local JSON). Missing associations are shown explicitly. Restart the server after
Python backend changes, then hard-refresh the page: refreshing alone can serve new JavaScript
against old API handlers. [Summary failure diagnosis](docs/run_summary_failure.md) documents
the reproduced stale-server 404 and successful recorded-media HTTP checks after restart.

Validation for this update: 128 dashboard/live-run tests and lint/format checks passed.
**No live browser checks were completed for this batch:** browser access was unavailable.
HTTP/WebSocket and Node checks passed; visual playback, wedge/pin appearance and Chrome's
download interaction remain pending. See the [review handoff](docs/demo_review_handoff.md).

## Client demo documents

- [Demo run order](docs/demo_run_order.md): exact clicks, what to say, backup plan, honest answers
- [Results sheet](docs/client_results_sheet.md): every number, labelled MEASURED, SIMULATED or PROJECTED
- [Known issues](docs/known_issues.md) and [licences](docs/licences.md)
- [Pre-demo review](REVIEW.md)

## Project docs

- [GitHub workflow](GITHUB.md)
- [Repository rules](docs/rules.md) and [current project state](docs/memory.md)
- [Requirements](docs/prd.md), [architecture](docs/architecture.md), and [design](docs/design.md)
