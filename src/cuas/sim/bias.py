"""A mis-aligned mast: every bearing one station publishes is off by a fixed azimuth.

A robustness check, never part of a baseline run. It wraps the sensor bus, so the simulator and
the pipeline are unchanged; only what the gateway receives differs.
"""

from collections.abc import AsyncIterator

from cuas.bus import Bus
from cuas.geometry import wrap_azimuth
from cuas.schemas import BearingDetection, Message


class MastBias:
    """Publishes through to ``bus``, turning ``station_id``'s bearings by ``offset_deg``."""

    def __init__(self, bus: Bus, station_id: str, offset_deg: float) -> None:
        self._bus = bus
        self._station_id = station_id
        self._offset_deg = offset_deg

    async def publish(self, topic: str, msg: Message) -> None:
        if isinstance(msg, BearingDetection) and msg.station_id == self._station_id:
            turned = wrap_azimuth(msg.azimuth_deg + self._offset_deg)
            msg = msg.model_copy(update={"azimuth_deg": turned})
        await self._bus.publish(topic, msg)

    def subscribe(self, topic: str) -> AsyncIterator[Message]:
        return self._bus.subscribe(topic)

    async def close(self) -> None:
        await self._bus.close()
