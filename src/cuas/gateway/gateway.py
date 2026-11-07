"""The ingest gateway (docs/design.md A4): nothing reaches the tracker without passing it.

Each message is checked from its JSON text, as it would arrive over a network, so a message
built without validation is caught too.
"""

import logging
from collections.abc import AsyncIterator, Callable

from pydantic import ValidationError

from cuas.bus import Bus
from cuas.config import GatewaySettings, SiteConfig
from cuas.schemas import (
    BearingDetection,
    Message,
    PicketAlert,
    RejectedMessage,
    SensorStatus,
)
from cuas.schemas.topics import GATEWAY_ACCEPTED, GATEWAY_REJECTED

log = logging.getLogger(__name__)

INGEST_TYPES: dict[str, type[Message]] = {
    model.__name__: model for model in (BearingDetection, PicketAlert, SensorStatus)
}


def sensor_id(message: Message) -> str:
    """The ID a sensor reports under: ``st1.rgb`` for a camera, ``pk4`` for a picket."""
    if isinstance(message, BearingDetection):
        return f"{message.station_id}.{message.sensor}"
    if isinstance(message, PicketAlert):
        return message.picket_id
    return message.sensor_id


def known_sensors(site: SiteConfig) -> frozenset[str]:
    """Every sensor ID the site configures. Sensor positions come from the site, never a message."""
    cameras = {f"{s.id}.{kind}" for s in site.stations for kind in site.sensors}
    return frozenset(cameras | {p.id for p in site.pickets})


class Gateway:
    """Validates schema, timestamp and sender. Only ``now`` comes from the clock."""

    def __init__(
        self,
        settings: GatewaySettings,
        known: frozenset[str],
        now: Callable[[], float],
    ) -> None:
        self._settings = settings
        self._known = known
        self._now = now

    def admit(self, kind: str, raw: str) -> Message | RejectedMessage:
        """Check one message given its type name and JSON text."""
        model = INGEST_TYPES.get(kind)
        if model is None:
            return _reject(f"schema: unexpected message type {kind!r}", raw)
        try:
            message = model.model_validate_json(raw)
        except ValidationError as error:
            return _reject(f"schema: {error.error_count()} invalid field(s)", raw)
        now = self._now()
        if message.t - now > self._settings.max_future_s:
            return _reject(
                f"future: t={message.t} is {message.t - now:.3f} s ahead", raw
            )
        if now - message.t > self._settings.max_age_s:
            return _reject(f"stale: t={message.t} is {now - message.t:.3f} s old", raw)
        if sensor_id(message) not in self._known:
            return _reject(f"unknown_sensor: {sensor_id(message)}", raw)
        return message


def _reject(reason: str, raw: str) -> RejectedMessage:
    log.warning("rejected %s", reason)
    return RejectedMessage(reason=reason, raw=raw)


async def run_gateway(
    gateway: Gateway, source: AsyncIterator[Message], sink: Bus
) -> None:
    """Check every message from the sensor network, in arrival order."""
    async for message in source:
        result = gateway.admit(type(message).__name__, message.model_dump_json())
        rejected = isinstance(result, RejectedMessage)
        await sink.publish(GATEWAY_REJECTED if rejected else GATEWAY_ACCEPTED, result)
