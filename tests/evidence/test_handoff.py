"""The hand-off package: its committed schema, and a valid package for every alert of a run."""

from pathlib import Path

import pytest

from cuas.evidence.handoff import HandoffPackage, handoff_schema_text
from cuas.evidence.keeper import EvidenceKeeper
from cuas.evidence.store import EvidenceStore
from cuas.evidence.verify import verify_chain
from cuas.schemas import ThreatAssessment
from cuas.sim.scenario import load_scenario

SCHEMA = Path(__file__).resolve().parents[2] / "docs" / "handoff.schema.json"


def test_the_committed_schema_matches_the_model() -> None:
    """Regenerate with ``uv run python scripts/record_stream.py --schema``."""
    assert SCHEMA.read_text(encoding="utf-8") == handoff_schema_text()


@pytest.mark.parametrize("scenario_id", ["s1", "s2"])
async def test_every_alert_exports_a_valid_package(
    record_pipeline, tmp_path: Path, config_dir: Path, scenario_id: str
) -> None:
    _, _, controlled, _ = await record_pipeline(scenario_id)
    labels = load_scenario(config_dir, scenario_id).metadata.zone_labels
    keeper = EvidenceKeeper(EvidenceStore(tmp_path), "run-1", labels)
    for message in controlled:
        keeper.ingest(message)
    exports = keeper.finish()
    alerts = {
        m.alert_id
        for m in controlled
        if isinstance(m, ThreatAssessment) and m.alert_id is not None
    }
    assert alerts and [r.alert_id for r in exports] == sorted(alerts)
    for record in exports:
        package = HandoffPackage.model_validate_json(
            (tmp_path / record.files[0].path).read_bytes()
        )
        assert package.alert.alert_id == record.alert_id
        assert package.alert.track_history and package.alert.last_position
        assert package.alert.zone_label in {None, *labels.model_dump().values()}
    assert verify_chain(tmp_path).problems == []
