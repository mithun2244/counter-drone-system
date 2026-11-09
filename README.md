# Counter Drone System

Passive counter-drone detection demo. The simulator generates the site geometry and sensor observations. Recorded-media mode runs the detectors and classifier on public RGB, thermal and audio recordings.

## Run the operator dashboard

From the repository root, with Python 3.11 and `uv` available:

```sh
uv sync
uv run python scripts/run_demo.py --dashboard
```

Open [the operator dashboard](http://127.0.0.1:8000/). It works offline and loads nothing from the internet.

1. In the top bar, select **Fictional Processing Plant**, choose **S1**, and click **Start monitoring**. Use **1× / 2× / 5×** and **Pause** to control the simulated clock.
2. Watch the map: pickets flash and amber wedges show engines heard but not yet placed. Tracks appear as dots with trails, labelled with their level. Tick **Bearing rays** to see the station bearings, and **Close-up** to fit the map to the site.
3. The **Alert queue** on the right lists alerts in the server's ranking, with time to impact counting down. **System status**, on the left, shows coverage, each station's sensors, faults and the evidence head.
4. Click a card. Its track gets a ring on the map, and **Selected alert** opens below the queue with the track's estimated position, altitude, ground speed, course, contributing stations and coasting state. Values that cannot be shown say why.
5. With **Recorded media** ticked before starting (Fictional Stadium, S2), the selected alert's video plays over the upper right of the map. Pick a camera with its tab, and collapse or expand it with **−** / **+**. Under **Evidence**, **Recorded audio** plays each station's clean source audio.
6. On a card, **Confirm** or **Dismiss** saves a label in the evidence chain, and **Export hand-off JSON** saves a mock hand-off package and shows its path and SHA-256 on the card and in the evidence section.
7. After the run, check its evidence with `uv run cuas verify runs/<run_id>`. The run folder is shown in **System status**.

Without `data/basemap/portsmouth.json` (from `scripts/fetch_basemap.py`) the map draws a local grid. For recorded-media runs, prepare the local recordings and model weights as described in the [dashboard contract](docs/dashboard_contract.md) and [data source notes](data/README.md). The [reference page](http://127.0.0.1:8000/reference/) is a minimal independent check of the same contract. See [phase status and acceptance checks](docs/phases.md) for Phase 5 acceptance and the Phase 6 plan.

## Project docs

- [GitHub workflow](GITHUB.md)
- [Repository rules](docs/rules.md) and [current project state](docs/memory.md)
- [Requirements](docs/prd.md), [architecture](docs/architecture.md), and [design](docs/design.md)
