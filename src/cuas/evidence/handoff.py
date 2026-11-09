"""The alert snapshot and the mock hand-off package (docs/design.md A11, docs/handoff.schema.json).

A snapshot is what was known about an alert at one moment. The package wraps the latest snapshot
with the operator's labels and where the alert sits in the evidence chain. It is a JSON file
only: the demo never sends it anywhere.
"""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cuas.schemas import FileRef

PACKAGE_VERSION = 1
MOCK_NOTE = "Mock hand-off: a JSON file only, never sent. Detect and report only."


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HistoryPoint(Model):
    """One published track position. ``n_stations`` 0 means a prediction while coasting."""

    track_id: str
    t: float
    x: float
    y: float
    z: float
    n_stations: int


class Clip(Model):
    """A recording behind the alert's look or sound evidence: ``source`` is ``station.sensor``."""

    source: str
    file: FileRef


class AlertSnapshot(Model):
    """Positions in local ENU metres from the site centre; times in simulated seconds."""

    alert_id: str
    t: float
    track_ids: list[str]
    level: Literal["red", "amber", "info"]
    """The level now. An alert can fall back to info, for example once its track is lost."""
    highest_level: Literal["red", "amber"]
    """The highest level the alert reached."""
    score: float
    time_to_impact_s: float | None
    zone_id: str | None
    zone_label: str | None
    reasons: list[str]
    p_drone: float | None
    p_bird: float | None
    p_attack_drone: float | None
    last_position: HistoryPoint | None
    track_history: list[HistoryPoint]
    clips: list[Clip]


class LabelEntry(Model):
    label: Literal["confirm", "dismiss"]
    t: float
    seq: int


class ChainRef(Model):
    seq: int
    record_hash: str


class HandoffPackage(Model):
    mock: Literal[True] = True
    note: str = MOCK_NOTE
    package_version: Literal[1] = PACKAGE_VERSION
    run_id: str
    exported_t: float
    alert: AlertSnapshot
    labels: list[LabelEntry]
    alert_record_hash: str
    """The chain record written when the alert was raised."""
    chain_head: ChainRef
    """The newest record before this export's own. Deleting newer records cannot hide it."""


def handoff_schema_text() -> str:
    """``docs/handoff.schema.json``, generated from the model."""
    schema = HandoffPackage.model_json_schema()
    return json.dumps(schema, indent=1, sort_keys=True) + "\n"
