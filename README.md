# Counter Drone System

Passive counter-drone detection demo. The simulator generates the site geometry and sensor observations. Recorded-media mode runs the detectors and classifier on public RGB, thermal and audio recordings.

## Run the reference dashboard

From the repository root, with Python 3.11 and `uv` available:

```sh
uv sync
uv run python scripts/run_demo.py --dashboard
```

Open [the reference dashboard](http://127.0.0.1:8000/reference/). Select **Fictional Processing Plant**, choose **S1**, and click **Start monitoring**. For recorded-media runs, prepare the local recordings and model weights as described in the [dashboard contract](docs/dashboard_contract.md) and [data source notes](data/README.md).

The Phase 5 reference page is available for testing. See [phase status and acceptance checks](docs/phases.md) for the full operator dashboard and the Phase 6 plan.

## Project docs

- [GitHub workflow](GITHUB.md)
- [Repository rules](docs/rules.md) and [current project state](docs/memory.md)
- [Requirements](docs/prd.md), [architecture](docs/architecture.md), and [design](docs/design.md)
