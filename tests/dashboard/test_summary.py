"""Completed-run history is independent of the final live alert queue."""

import json
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from cuas.dashboard.contract import EvidenceEvent, RunInfo
from cuas.dashboard.replay import ReplayLauncher
from cuas.dashboard.server import Hub, create_app
from cuas.dashboard.summary import RunSummary
from cuas.schemas import ClueEvidence, TrackClass
from tests.dashboard.test_cues import confirmed, ray
from tests.dashboard.test_frames import threat


def test_summary_ui():
    node = shutil.which("node")
    if node:
        subprocess.run([node, "tests/dashboard/summary_ui.cjs"], check=True)


def test_raw_history_links_only_backend_evidence_and_keeps_peak():
    summary = RunSummary()
    summary.ingest(confirmed(9, (100, 200, 80)))
    summary.ingest(threat("trk-1", 9, "red", "alert-1"))
    summary.ingest(threat("trk-1", 10, "amber", "alert-1"))
    detection = ray(10, 30).model_copy(
        update={"snapshot_ref": "clip:1", "class_probs": {"drone": 0.9}}
    )
    summary.ingest(detection)
    summary.ingest(
        TrackClass(
            track_id="trk-1",
            t=10,
            p_drone=0.9,
            p_bird=0.1,
            p_attack_drone=0.1,
            evidence=ClueEvidence(),
            looks={"st2.thermal": "clip:1"},
        )
    )
    result = summary.result()
    assert result["unique_alert_tracks"] == 1
    latest = result["latest_detection"]
    assert (
        latest["t"],
        latest["track_id"],
        latest["classification"],
        latest["peak_level"],
    ) == (10, "trk-1", "drone", "red")
    assert latest["position"] == {"x": 100, "y": 200, "z": 80, "t": 9}
    summary.ingest(ray(12, 40))
    assert summary.result()["latest_detection"]["track_id"] is None
    assert "position" not in summary.result()["latest_detection"]
    assert summary.result()["last_position"]["t"] == 9


def test_no_detection_summary_api_manual_stop_and_new_run_reset(site):
    path = Path("docs/samples/edge_states.jsonl")
    hub = Hub(ReplayLauncher(path, site.simulation.tick_s))
    run = next(
        RunInfo.model_validate(json.loads(line))
        for line in path.read_text().splitlines()
        if json.loads(line)["type"] == "run"
    )
    with TestClient(create_app(hub)) as client:
        assert client.get("/api/run/summary").status_code == 404
        hub.publish(run)
        hub.summary.detect(5, "pk1", None)
        hub.publish(
            EvidenceEvent(
                run_id=run.run_id,
                seq=7,
                kind="alert",
                alert_id="a",
                t=5,
                record_hash="0" * 64,
            )
        )
        hub.publish(
            run.model_copy(update={"state": "ended", "ended_reason": "stopped"})
        )
        result = client.get("/api/run/summary").json()
        assert (
            client.get("/api/run/summary", params={"run_id": run.run_id}).json()
            == result
        )
        assert (
            client.get("/api/run/summary", params={"run_id": "wrong-run"}).status_code
            == 409
        )
        assert result["ended_reason"] == "stopped"
        assert result["latest_detection"]["t"] == 5
        assert result["evidence_records"] == 7
        assert client.get("/api/run/summary").json() == result
        hub.publish(run.model_copy(update={"run_id": "next", "state": "running"}))
        result = client.get("/api/run/summary").json()
        assert result["latest_detection"] is None
        assert result["unique_alert_tracks"] == result["evidence_records"] == 0
        hub.publish(
            run.model_copy(
                update={"run_id": "next", "state": "ended", "ended_reason": "completed"}
            )
        )
        assert client.get("/api/run/summary").json()["active_alerts"] == 0
