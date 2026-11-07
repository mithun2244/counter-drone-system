"""Simulated acoustic pickets: early warning when an engine is heard (docs/design.md A2)."""

import heapq
import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from cuas.config import EngineSettings, PicketSettings, Placement, TargetType
from cuas.geometry import bearing_to, wrap_azimuth
from cuas.schemas import PicketAlert, SensorStatus
from cuas.sim.rng import stream
from cuas.sim.station import LookSource
from cuas.sim.truth import PicketTruth

Report = tuple[PicketAlert, PicketTruth]


def guess_engine(
    true_type: str,
    engine_types: Sequence[str],
    accuracy: float,
    rng: np.random.Generator,
) -> tuple[str, dict[str, float]]:
    """A noisy engine guess and its probabilities.

    MOCK: stands in for the audio classifier when no recorded media is in use. It is
    deliberately imperfect, because a perfect guess would hand the true target type to
    everything downstream.
    """
    others = [engine for engine in engine_types if engine != true_type]
    correct, pick = rng.random(2).tolist()
    if not others:
        return true_type, {true_type: 1.0}
    guess = true_type if correct < accuracy else others[int(pick * len(others))]
    share = (1.0 - accuracy) / len(others)
    return guess, {e: accuracy if e == guess else share for e in sorted(engine_types)}


@dataclass(frozen=True)
class _Heard:
    """A report waiting out the picket's processing delay."""

    heard_t: float
    target_id: str
    target_type: TargetType
    true_bearing_deg: float
    reported_bearing_deg: float
    distance_m: float
    hearing_radius_m: float
    loudness: float
    engine_type: str
    guessed_engine_type: str
    engine_type_probs: dict[str, float]


class PicketSim:
    """One picket. Hears engines within a wind-reduced radius and reports after a delay."""

    def __init__(
        self,
        picket: Placement,
        settings: PicketSettings,
        tick_s: float,
        wind_factor: float,
        seed: int,
        media: LookSource | None = None,
    ) -> None:
        self._media = media
        self._picket = picket
        self._settings = settings
        self._tick_s = tick_s
        self._wind_factor = wind_factor
        self._seed = seed
        self._engine_types = sorted({e.type for e in settings.engines.values()})
        self._report_every_ticks = round(settings.report_period_s / tick_s)
        self._streams: dict[str, np.random.Generator] = {}
        self._next_report_tick: dict[str, int] = {}
        self._pending: list[tuple[int, int, _Heard]] = []
        self._heard_count = 0

    def _stream(self, target_id: str) -> np.random.Generator:
        if target_id not in self._streams:
            self._streams[target_id] = stream(
                self._seed, "picket", self._picket.id, target_id
            )
        return self._streams[target_id]

    def listen(
        self,
        target_id: str,
        target_type: TargetType,
        position: Sequence[float],
        tick: int,
        t: float,
    ) -> None:
        """Queue a report if this target's engine can be heard on this tick."""
        engine = self._settings.engines.get(target_type)
        if engine is None:
            return  # no engine, nothing to hear
        # Drawn every tick, heard or not, so noise lines up across runs that differ in range.
        rng = self._stream(target_id)
        delay_s = rng.uniform(*self._settings.delay_s)
        heard = self._hear(target_id, target_type, engine, position, t, rng)
        if heard is None or tick < self._next_report_tick.get(target_id, 0):
            return
        self._next_report_tick[target_id] = tick + self._report_every_ticks
        due_tick = tick + math.ceil(delay_s / self._tick_s)
        self._heard_count += 1
        heapq.heappush(self._pending, (due_tick, self._heard_count, heard))

    def _hear(
        self,
        target_id: str,
        target_type: TargetType,
        engine: EngineSettings,
        position: Sequence[float],
        t: float,
        rng: np.random.Generator,
    ) -> _Heard | None:
        settings = self._settings
        error_limit = settings.bearing_error_deg
        bearing_error = rng.uniform(-error_limit, error_limit)
        loudness_noise = settings.loudness_sigma * rng.standard_normal()
        guess, probs = guess_engine(
            engine.type, self._engine_types, settings.engine_guess_accuracy, rng
        )
        azimuth, _, distance_m = bearing_to(self._picket.position_enu_m, position)
        radius_m = engine.hearing_radius_m * self._wind_factor
        if distance_m > radius_m:
            return None
        if self._media is not None:
            real = self._media.hear_engine(
                self._picket.id, target_id, target_type, distance_m, t
            )
            if real is not None:
                guess, probs = max(real, key=real.get), real
        return _Heard(
            heard_t=t,
            target_id=target_id,
            target_type=target_type,
            true_bearing_deg=azimuth,
            reported_bearing_deg=wrap_azimuth(azimuth + float(bearing_error)),
            distance_m=distance_m,
            hearing_radius_m=radius_m,
            # MOCK: a simple falloff with distance, also when recorded media is in use.
            loudness=max(
                0.0, min(1.0, 1.0 - distance_m / radius_m + float(loudness_noise))
            ),
            engine_type=engine.type,
            guessed_engine_type=guess,
            engine_type_probs=probs,
        )

    def due(self, tick: int, t: float) -> list[Report]:
        """Reports whose delay has passed. Their ``t`` is now, when they are published."""
        reports = []
        while self._pending and self._pending[0][0] <= tick:
            _, _, heard = heapq.heappop(self._pending)
            reports.append(self._report(heard, t))
        return reports

    def _report(self, heard: _Heard, t: float) -> Report:
        alert = PicketAlert(
            picket_id=self._picket.id,
            t=t,
            bearing_deg=heard.reported_bearing_deg,
            loudness=heard.loudness,
            engine_type_probs=heard.engine_type_probs,
        )
        truth = PicketTruth(
            t=t,
            heard_t=heard.heard_t,
            target_id=heard.target_id,
            target_type=heard.target_type,
            picket_id=self._picket.id,
            bearing_deg=heard.true_bearing_deg,
            distance_m=heard.distance_m,
            hearing_radius_m=heard.hearing_radius_m,
            engine_type=heard.engine_type,
            guessed_engine_type=heard.guessed_engine_type,
        )
        return alert, truth

    def status(self, t: float) -> SensorStatus:
        # MOCK: simulated sensors never fail.
        return SensorStatus(
            sensor_id=self._picket.id,
            ok=True,
            visibility_factor=self._wind_factor,
            t=t,
        )
