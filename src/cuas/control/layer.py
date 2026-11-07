"""Feeds the shared tracker and the sector tracker from the gateway's accepted messages, in order.

Bearings within ``batch_window_s`` of each other are triangulated together, so a batch is processed
once a later message shows that its time has passed. Sensor statuses arrive every second, which
keeps time moving when nothing is seen.
"""

from collections.abc import Mapping

from cuas.config import TrackerSettings
from cuas.control.sectors import SectorTracker
from cuas.control.tracker import SharedTracker
from cuas.schemas import BearingDetection, Message, PicketAlert
from cuas.schemas.base import Vector3


class ControlLayer:
    def __init__(
        self,
        settings: TrackerSettings,
        stations: Mapping[str, Vector3],
        pickets: Mapping[str, Vector3],
        picket_half_width_deg: float,
    ) -> None:
        self._settings = settings
        self._stations = stations
        self._pickets = pickets
        self._picket_half_width_deg = picket_half_width_deg
        self._tracker = SharedTracker(settings, stations)
        self._sectors = SectorTracker(settings.sector_lost_after_s)
        self._batch_t: float | None = None
        self._pending: list[BearingDetection] = []

    def ingest(self, message: Message) -> list[Message]:
        """Take one accepted message. Returns whatever it makes ready to publish."""
        out: list[Message] = []
        if (
            self._batch_t is not None
            and message.t - self._batch_t >= self._settings.batch_window_s
        ):
            out.extend(self._process())
        if self._batch_t is None:
            self._batch_t = message.t
        if isinstance(message, BearingDetection):
            self._pending.append(message)
        elif isinstance(message, PicketAlert):
            out.append(
                self._sectors.report(
                    message.picket_id,
                    self._pickets[message.picket_id],
                    message.t,
                    message.bearing_deg,
                    self._picket_half_width_deg,
                )
            )
        return out

    def flush(self) -> list[Message]:
        """Process the last batch, once no more messages will come."""
        return self._process() if self._batch_t is not None else []

    def _process(self) -> list[Message]:
        t, bearings = self._batch_t, self._pending
        self._batch_t, self._pending = None, []
        out: list[Message] = list(self._tracker.update(t, bearings))
        for bearing in bearings:
            if bearing.sensor in self._settings.position_sensors:
                continue
            if self._tracker.accounts_for(bearing):
                continue  # heard, and already placed in 3D by the cameras
            out.append(
                self._sectors.report(
                    f"{bearing.station_id}.{bearing.sensor}",
                    self._stations[bearing.station_id],
                    t,
                    bearing.azimuth_deg,
                    self._settings.acoustic_sector_sigmas * bearing.sigma_deg,
                )
            )
        out.extend(self._sectors.expire(t))
        return out
