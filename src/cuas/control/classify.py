"""Classifier fusion (docs/design.md A7): look, move and sound become one P(drone) per track.

Clues are matched to tracks by geometry only, with the tracker's bearing gate. Missing clues are
skipped, and every clue is held inside [floor, 1 - floor], so no single one is ever certain.
"""

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from cuas.config import ClassifySettings
from cuas.control.association import assign, bearing_distance2
from cuas.control.behaviour import Features, Fix, MoveClue
from cuas.geometry import angle_difference_deg, bearing_to
from cuas.schemas import BearingDetection, ClueEvidence, PicketAlert, Track, TrackClass
from cuas.schemas.base import Vector3

CAMERAS = ("rgb", "thermal", "zoom")
UNKNOWN_ENGINE = 0.5  # no engine heard: no evidence either way about piston or electric
PISTON = "piston"


def logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def fuse(
    prior: float,
    clues: Mapping[str, float | None],
    weights: Mapping[str, float],
    floor: float,
) -> float:
    """``logit(P) = logit(prior) + sum w_m (logit(p_m) - logit(prior))`` over present clues."""
    total = logit(prior)
    for name, p in clues.items():
        if p is not None:
            held = min(max(p, floor), 1.0 - floor)
            total += weights[name] * (logit(held) - logit(prior))
    return 1.0 / (1.0 + math.exp(-total))


def look_probability(class_probs: Mapping[str, float]) -> float | None:
    """The drone share of a confirmed look. An all-zero look is unconfirmed, not evidence."""
    total = sum(class_probs.values())
    return class_probs.get("drone", 0.0) / total if total > 0.0 else None


def sound_probability(class_probs: Mapping[str, float]) -> float | None:
    """Anything but background is an engine or rotor heard: P(drone) from sound."""
    total = sum(class_probs.values())
    return 1.0 - class_probs.get("background", 0.0) / total if total > 0.0 else None


def piston_share(class_probs: Mapping[str, float]) -> float | None:
    engine, electric = (
        class_probs.get("engine", 0.0),
        class_probs.get("electric_drone", 0.0),
    )
    return engine / (engine + electric) if engine + electric > 0.0 else None


@dataclass
class _Evidence:
    move: MoveClue
    looks: list[float] = field(default_factory=list)
    zoom_looks: list[tuple[float, float]] = field(default_factory=list)
    wide_frames: set[str] = field(default_factory=set)
    sounds: list[float] = field(default_factory=list)
    piston: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class Classified:
    """A track's class, with the behaviour behind it for the threat reasons."""

    track: Track
    track_class: TrackClass
    features: Features | None
    move_reason: str | None
    """``seen hovering``, ``sustained fast straight flight`` or ``wandering flight``."""
    engine_heard: bool
    velocity: np.ndarray | None = None
    """Fitted over recent fresh fixes; ``None`` before enough history."""


class Classifier:
    def __init__(
        self,
        settings: ClassifySettings,
        gate_sigmas: float,
        stations: Mapping[str, Vector3],
        pickets: Mapping[str, Vector3],
        picket_reach_m: float,
        picket_half_width_deg: float,
    ) -> None:
        self._settings = settings
        self._gate_sigmas = gate_sigmas
        self._stations = {k: np.asarray(v, dtype=float) for k, v in stations.items()}
        self._pickets = {k: np.asarray(v, dtype=float) for k, v in pickets.items()}
        self._reach_m = picket_reach_m
        self._half_width = picket_half_width_deg
        self._evidence: dict[str, _Evidence] = {}
        self._alerts: list[PicketAlert] = []

    def heard(self, alert: PicketAlert) -> None:
        self._alerts.append(alert)

    def update(
        self, t: float, tracks: Sequence[Track], bearings: Sequence[BearingDetection]
    ) -> list[Classified]:
        live = [tr for tr in tracks if tr.status != "lost"]
        for track in tracks:
            if track.status == "lost":
                self._evidence.pop(track.track_id, None)
        for track in live:
            evidence = self._evidence.setdefault(
                track.track_id, _Evidence(MoveClue(self._settings.move))
            )
            if (
                track.status == "confirmed" and track.n_stations >= 2
            ):  # fresh fixes only
                evidence.move.add(
                    Fix(
                        t,
                        np.asarray(track.position_enu_m),
                        np.asarray(track.velocity_mps),
                    )
                )
        self._match_bearings(t, live, bearings)
        self._match_alerts(t, live)
        return [self._classify(t, track) for track in live]

    def _match_bearings(
        self, t: float, live: Sequence[Track], bearings: Sequence[BearingDetection]
    ) -> None:
        groups: defaultdict[tuple[str, str], list[BearingDetection]] = defaultdict(list)
        for bearing in bearings:
            if bearing.class_probs:
                groups[(bearing.station_id, bearing.sensor)].append(bearing)
        # Zoom last, so every wide frame of this batch is known before a zoom look is counted.
        order = sorted(groups.items(), key=lambda g: (g[0][1] == "zoom", g[0]))
        for (station_id, sensor), found in order:
            origin = self._stations[station_id]
            distances2 = np.array(
                [
                    [
                        bearing_distance2(
                            np.asarray(tr.position_enu_m),
                            np.asarray(tr.covariance)[:3, :3],
                            origin,
                            b,
                        )
                        for b in found
                    ]
                    for tr in live
                ]
            ).reshape(len(live), len(found))
            for row, column in assign(distances2, self._gate_sigmas):
                self._add_bearing(t, live[row].track_id, sensor, found[column])

    def _add_bearing(
        self, t: float, track_id: str, sensor: str, bearing: BearingDetection
    ) -> None:
        evidence = self._evidence[track_id]
        if sensor in CAMERAS:
            p = look_probability(bearing.class_probs)
            if sensor != "zoom":
                if bearing.snapshot_ref is not None:
                    evidence.wide_frames.add(bearing.snapshot_ref)
                if p is not None:
                    evidence.looks.append(p)
            elif p is not None and bearing.snapshot_ref not in evidence.wide_frames:
                evidence.zoom_looks.append(
                    (t, p)
                )  # a frame already seen wide adds nothing
            return
        p = sound_probability(bearing.class_probs)
        if p is not None:
            evidence.sounds.append(p)
        if (share := piston_share(bearing.class_probs)) is not None:
            evidence.piston.append(share)

    def _match_alerts(self, t: float, live: Sequence[Track]) -> None:
        """A picket heard an engine in a wedge: every track inside wedge and reach was heard."""
        alerts, self._alerts = self._alerts, []
        for alert in alerts:
            origin = self._pickets[alert.picket_id]
            for track in live:
                azimuth, _, distance = bearing_to(origin, track.position_enu_m)
                off = abs(angle_difference_deg(azimuth, alert.bearing_deg))
                if off <= self._half_width and distance <= self._reach_m:
                    evidence = self._evidence[track.track_id]
                    evidence.sounds.append(self._settings.picket_engine_heard)
                    total = sum(alert.engine_type_probs.values())
                    if total > 0.0:
                        evidence.piston.append(
                            alert.engine_type_probs.get(PISTON, 0.0) / total
                        )

    def _classify(self, t: float, track: Track) -> Classified:
        settings = self._settings
        evidence = self._evidence[track.track_id]
        clues = {
            "look": self._look(t, evidence),
            "move": evidence.move.p_move(),
            "sound": _mean(evidence.sounds),
        }
        p_drone = fuse(settings.prior, clues, settings.weights, settings.clue_floor)
        piston = _mean(evidence.piston)
        speed = float(np.linalg.norm(track.velocity_mps[:2]))
        fast = speed > settings.attack_speed_mps
        p_attack = (
            p_drone * (UNKNOWN_ENGINE if piston is None else piston) if fast else 0.0
        )
        message = TrackClass(
            track_id=track.track_id,
            t=t,
            p_drone=p_drone,
            p_bird=1.0 - p_drone,
            p_attack_drone=p_attack,
            evidence=ClueEvidence(**clues),
        )
        return Classified(
            track,
            message,
            evidence.move.latest,
            evidence.move.reason(),
            bool(evidence.sounds),
            evidence.move.velocity(),  # fitted to past fresh fixes, never a prediction
        )

    def _look(self, t: float, evidence: _Evidence) -> float | None:
        """Zoom looks replace wide-camera looks once zoom has watched for long enough."""
        zoom = evidence.zoom_looks
        if zoom and t - zoom[0][0] >= self._settings.zoom_look_after_s:
            return _mean([p for _, p in zoom])
        return _mean(evidence.looks)


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None
