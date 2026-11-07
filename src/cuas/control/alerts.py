"""Alerts: a track reaching amber or red, with an identity kept apart from the track's own.

- Only confirmed tracks are ever above ``info``.
- A level can rise only on a batch where the track had a fresh fix. A coasting track holds its
  level, says so in its reasons, and can never raise a new alert.
- A newly confirmed track continues the alert of a recently lost track if it first appears
  where that track was heading. Only lost tracks can be continued, each by at most one new
  track, so two drones flying together keep two alerts.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from cuas.config import AlertSettings
from cuas.control.association import assign
from cuas.control.threat import LEVELS, Assessment
from cuas.schemas import ThreatAssessment, Track

INFO = "info"
FRESH_STATIONS = 2


@dataclass
class _State:
    confirmed: bool = False
    alert_id: str | None = None
    level: str = INFO
    score: float = 0.0
    last_fresh_t: float | None = None


@dataclass(frozen=True)
class _Lost:
    alert_id: str
    t: float
    last_fresh_t: float
    position: np.ndarray
    velocity: np.ndarray
    sigma_m: float


class AlertKeeper:
    def __init__(self, settings: AlertSettings) -> None:
        self._settings = settings
        self._states: dict[str, _State] = {}
        self._lost: list[_Lost] = []
        self._raised = 0

    def update(
        self, t: float, tracks: Sequence[Track], assessments: Sequence[Assessment]
    ) -> list[ThreatAssessment]:
        by_track = {a.track_id: a for a in assessments}
        for track in tracks:
            if track.status == "lost":
                self._forget(track, t)
        self._lost = [
            lost for lost in self._lost if t - lost.t <= self._settings.relink_window_s
        ]
        live = [tr for tr in tracks if tr.status != "lost"]
        newly_confirmed = []
        for track in live:
            state = self._states.setdefault(track.track_id, _State())
            if track.status == "confirmed" and not state.confirmed:
                state.confirmed = True
                newly_confirmed.append(track)
        self._continue_alerts(t, newly_confirmed)
        return [self._assess(t, track, by_track[track.track_id]) for track in live]

    def _forget(self, track: Track, t: float) -> None:
        state = self._states.pop(track.track_id, None)
        if state is None or state.alert_id is None:
            return
        covariance = np.asarray(track.covariance)[:3, :3]
        self._lost.append(
            _Lost(
                state.alert_id,
                t,
                t if state.last_fresh_t is None else state.last_fresh_t,
                np.asarray(track.position_enu_m),
                np.asarray(track.velocity_mps),
                float(np.sqrt(np.linalg.eigvalsh(covariance).max())),
            )
        )

    def _continue_alerts(self, t: float, newly_confirmed: Sequence[Track]) -> None:
        """Each recently lost alert goes to at most one new track inside its reach."""
        if not newly_confirmed or not self._lost:
            return
        settings = self._settings
        reach2 = np.full((len(self._lost), len(newly_confirmed)), np.inf)
        for row, lost in enumerate(self._lost):
            expected = lost.position + lost.velocity * (t - lost.t)
            radius = min(
                settings.relink_gate_sigmas * lost.sigma_m,
                settings.relink_max_speed_mps * (t - lost.last_fresh_t)
                + settings.relink_margin_m,
            )
            for column, track in enumerate(newly_confirmed):
                gap = float(np.linalg.norm(np.asarray(track.position_enu_m) - expected))
                reach2[row, column] = (gap / radius) ** 2 if radius > 0.0 else np.inf
        taken = []
        for row, column in assign(reach2, 1.0):
            state = self._states[newly_confirmed[column].track_id]
            state.alert_id = self._lost[row].alert_id
            taken.append(row)
        self._lost = [lost for row, lost in enumerate(self._lost) if row not in taken]

    def _assess(self, t: float, track: Track, raw: Assessment) -> ThreatAssessment:
        state = self._states[track.track_id]
        fresh = track.n_stations >= FRESH_STATIONS
        level, score = (raw.level, raw.score) if state.confirmed else (INFO, raw.score)
        reasons = list(raw.reasons)
        if fresh:
            state.last_fresh_t = t
            state.level, state.score = level, score
        else:
            if LEVELS.index(level) > LEVELS.index(state.level):
                level = state.level  # a prediction alone can never raise the level
            score = min(score, state.score) if level == state.level else score
            if state.last_fresh_t is not None:
                reasons.append(f"no fresh fix for {t - state.last_fresh_t:.1f} s")
        if level != INFO and state.alert_id is None and fresh:
            self._raised += 1
            state.alert_id = f"alert-{self._raised}"
        return ThreatAssessment(
            track_id=track.track_id,
            score=score,
            level=level,
            zone=raw.zone,
            time_to_impact_s=raw.time_to_impact_s,
            reasons=tuple(reasons),
            alert_id=state.alert_id,
        )
