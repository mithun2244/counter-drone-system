"""The shared tracker (docs/design.md A6): camera bearings from several stations become 3D tracks.

It sees bearings and the stations' surveyed positions, nothing else. Each batch of bearings that
share a time goes through these steps:

1. Predict every track to the batch time.
2. Confirmed tracks claim rays first, at most one per station and sensor, by Hungarian assignment.
3. A confirmed track updates on any fix that passes triangulation.
4. Corroborated fixes from the remaining rays update a track within ``merge_radius_m``, or else
   start a tentative one. This is what stops duplicate tracks.
5. Tentative tracks claim what is left.

A fix is corroborated when it has 3 or more stations, or when no other camera ray is left
unexplained, so nothing could have paired differently. Only corroborated fixes confirm a track,
because rays from different targets can cross where nothing is: a ghost.
"""

import itertools
import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from cuas.config import TrackerSettings
from cuas.control.association import assign, bearing_distance2
from cuas.control.kalman import State, predict, start, update
from cuas.control.triangulation import Fix, Ray, explains, triangulate
from cuas.schemas import BearingDetection, Track
from cuas.schemas.base import Vector3

log = logging.getLogger(__name__)

TENTATIVE, CONFIRMED, LOST = "tentative", "confirmed", "lost"
CORROBORATING_STATIONS = 3


@dataclass(frozen=True)
class _Seen:
    bearing: BearingDetection
    ray: Ray


@dataclass
class _Track:
    track_id: str
    state: State
    status: str
    last_fix_t: float
    corroborated: list[float] = field(default_factory=list)
    n_stations: int = 0


class SharedTracker:
    def __init__(
        self, settings: TrackerSettings, stations: Mapping[str, Vector3]
    ) -> None:
        self._settings = settings
        self._origins = {sid: np.asarray(p, dtype=float) for sid, p in stations.items()}
        self._tracks: list[_Track] = []
        self._t: float | None = None
        self._started = 0

    def update(self, t: float, bearings: Sequence[BearingDetection]) -> list[Track]:
        """Take one batch of bearings at time ``t``. Returns every live track, and any lost now."""
        if self._t is not None and t < self._t:
            log.warning("ignored a batch at t=%s, after t=%s", t, self._t)
            return []
        dt = 0.0 if self._t is None else t - self._t
        self._t = t
        for track in self._tracks:
            track.state = predict(track.state, dt, self._settings.accel_sigma_mps2)
            track.n_stations = 0
        seen = self._camera_rays(bearings)
        free = set(range(len(seen)))
        self._update_confirmed(seen, free, t)
        self._start_or_merge(seen, free, t)
        self._update_tentative(seen, free, t)
        return self._publish(t)

    def accounts_for(self, bearing: BearingDetection) -> bool:
        """Whether a live track explains this bearing, for bearings that cannot place a target."""
        origin = self._origins[bearing.station_id]
        limit = self._settings.gate_sigmas**2
        return any(
            bearing_distance2(
                tr.state.position, tr.state.covariance[:3, :3], origin, bearing
            )
            <= limit
            for tr in self._tracks
        )

    def _camera_rays(self, bearings: Sequence[BearingDetection]) -> list[_Seen]:
        usable = [b for b in bearings if b.sensor in self._settings.position_sensors]
        usable.sort(
            key=lambda b: (b.station_id, b.sensor, b.azimuth_deg, b.elevation_deg)
        )
        return [
            _Seen(b, Ray.from_bearing(b, self._origins[b.station_id])) for b in usable
        ]

    def _claim(
        self, tracks: list[_Track], seen: list[_Seen], free: set[int]
    ) -> dict[int, list[int]]:
        """Each track's rays, at most one per station and sensor. Claimed rays leave ``free``."""
        groups: defaultdict[tuple[str, str], list[int]] = defaultdict(list)
        for index in sorted(free):
            groups[(seen[index].ray.station_id, seen[index].ray.sensor)].append(index)
        claims: defaultdict[int, list[int]] = defaultdict(list)
        for (station_id, _), indices in sorted(groups.items()):
            origin = self._origins[station_id]
            distances2 = np.array(
                [
                    [
                        bearing_distance2(
                            tr.state.position,
                            tr.state.covariance[:3, :3],
                            origin,
                            seen[i].bearing,
                        )
                        for i in indices
                    ]
                    for tr in tracks
                ]
            ).reshape(len(tracks), len(indices))
            for row, column in assign(distances2, self._settings.gate_sigmas):
                claims[row].append(indices[column])
                free.discard(indices[column])
        return claims

    def _update_confirmed(self, seen: list[_Seen], free: set[int], t: float) -> None:
        confirmed = [tr for tr in self._tracks if tr.status == CONFIRMED]
        for row, indices in sorted(self._claim(confirmed, seen, free).items()):
            fix = triangulate([seen[i].ray for i in indices], self._settings)
            if isinstance(fix, Fix):
                self._apply(confirmed[row], fix, t, corroborated=True)
            elif fix.reason == "one_station":
                free.update(indices)  # one station cannot place it; another track may

    def _start_or_merge(self, seen: list[_Seen], free: set[int], t: float) -> None:
        for members in self._candidates(seen, free):
            if not free.issuperset(members):
                continue
            fix = triangulate([seen[i].ray for i in members], self._settings)
            if not isinstance(fix, Fix):
                continue
            contested = len(free) != len(members)
            if len(fix.stations) < CORROBORATING_STATIONS and contested:
                continue
            free.difference_update(members)
            near = self._nearest_within(fix.position, self._settings.merge_radius_m)
            if near is not None:
                self._apply(near, fix, t, corroborated=True)
            else:
                self._start(fix, t)

    def _candidates(self, seen: list[_Seen], free: set[int]) -> list[tuple[int, ...]]:
        """Every point two free rays agree on, with the free rays that pass through it.

        Best first: the most stations, then the most rays, then the closest fit.
        """
        pool = sorted(free)
        found = []
        for a, b in itertools.combinations(pool, 2):
            if seen[a].ray.station_id == seen[b].ray.station_id:
                continue
            pair = triangulate([seen[a].ray, seen[b].ray], self._settings)
            if not isinstance(pair, Fix):
                continue
            closest: dict[tuple[str, str], tuple[float, int]] = {}
            for i in pool:
                distance = explains(seen[i].ray, pair.position, self._settings)
                key = (seen[i].ray.station_id, seen[i].ray.sensor)
                if distance is not None and (
                    key not in closest or distance < closest[key][0]
                ):
                    closest[key] = (distance, i)
            if not closest:
                continue
            members = tuple(sorted(i for _, i in closest.values()))
            stations = {seen[i].ray.station_id for i in members}
            mean = sum(d for d, _ in closest.values()) / len(closest)
            found.append((-len(stations), -len(members), mean, members))
        found.sort()
        return [members for *_, members in found]

    def _update_tentative(self, seen: list[_Seen], free: set[int], t: float) -> None:
        waiting = [
            tr for tr in self._tracks if tr.status == TENTATIVE and tr.last_fix_t < t
        ]
        claims = self._claim(waiting, seen, free)
        uncontested = not free
        for row, indices in sorted(claims.items()):
            fix = triangulate([seen[i].ray for i in indices], self._settings)
            if isinstance(fix, Fix):
                corroborated = (
                    len(fix.stations) >= CORROBORATING_STATIONS or uncontested
                )
                self._apply(waiting[row], fix, t, corroborated)

    def _nearest_within(self, position: np.ndarray, radius_m: float) -> _Track | None:
        distances = [
            (float(np.linalg.norm(tr.state.position - position)), index)
            for index, tr in enumerate(self._tracks)
        ]
        inside = [(d, index) for d, index in distances if d < radius_m]
        return self._tracks[min(inside)[1]] if inside else None

    def _apply(self, track: _Track, fix: Fix, t: float, corroborated: bool) -> None:
        track.state = update(track.state, fix.position, fix.covariance)
        track.last_fix_t = t
        track.n_stations = len(fix.stations)
        if corroborated:
            track.corroborated.append(t)

    def _start(self, fix: Fix, t: float) -> None:
        self._started += 1
        state = start(
            fix.position, fix.covariance, self._settings.birth_speed_sigma_mps
        )
        track = _Track(f"trk-{self._started}", state, TENTATIVE, t, [t])
        track.n_stations = len(fix.stations)
        self._tracks.append(track)

    def _publish(self, t: float) -> list[Track]:
        settings = self._settings
        published, alive = [], []
        for track in self._tracks:
            track.corroborated = [
                u for u in track.corroborated if t - u <= settings.confirm_window_s
            ]
            if (
                track.status == TENTATIVE
                and len(track.corroborated) >= settings.confirm_fixes
            ):
                track.status = CONFIRMED
            lost = t - track.last_fix_t > settings.lost_after_s
            published.append(_message(track, t, LOST if lost else track.status))
            if not lost:
                alive.append(track)
        self._tracks = alive
        return published


def _message(track: _Track, t: float, status: str) -> Track:
    covariance = track.state.covariance
    return Track(
        track_id=track.track_id,
        t=t,
        position_enu_m=tuple(float(v) for v in track.state.position),
        velocity_mps=tuple(float(v) for v in track.state.velocity),
        covariance=tuple(tuple(float(v) for v in row) for row in covariance),
        n_stations=0 if status == LOST else track.n_stations,
        status=status,
    )
