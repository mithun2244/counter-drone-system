import math
import subprocess
import sys
from itertools import combinations
from pathlib import Path

import yaml

import cuas

ROOT = Path(__file__).resolve().parents[1]


def test_run_demo_loads_valid_site() -> None:
    assert cuas.__doc__

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_demo.py")],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "hello" in result.stdout
    assert "3 stations, 8 pickets, 3 zones" in result.stdout

    site = yaml.safe_load((ROOT / "config" / "site.yaml").read_text(encoding="utf-8"))

    stations = [s["position_enu_m"] for s in site["stations"]]
    assert len(stations) == 3
    for a, b in combinations(stations, 2):
        assert 450 <= math.dist(a[:2], b[:2]) <= 550

    pickets = [p["position_enu_m"] for p in site["pickets"]]
    assert len(pickets) == 8
    for x, y, _ in pickets:
        assert abs(math.hypot(x, y) - 3000) <= 1

    assert {z["id"]: z["weight"] for z in site["zones"]} == {
        "critical": 1.0,
        "important": 0.6,
        "perimeter": 0.3,
    }
