"""Wires the ingest gateway and the control layer between buses (docs/architecture.md section 5).

    sensor bus -> gateway -> ingest bus -> control layer -> control bus

Each stage reads one bus and writes the next, so nothing reaches the tracker without passing the
gateway, and the stages can shut down in order. Ground truth never comes here.
"""

import asyncio
from collections.abc import AsyncIterator, Callable

from cuas.bus import WILDCARD, Bus
from cuas.config import SiteConfig
from cuas.control.layer import ControlLayer
from cuas.gateway.gateway import Gateway, known_sensors, run_gateway
from cuas.schemas import Message, Track
from cuas.schemas.topics import GATEWAY_ACCEPTED, SECTOR_TRACK, TRACK


def control_layer(site: SiteConfig) -> ControlLayer:
    return ControlLayer(
        site.tracker,
        {s.id: s.position_enu_m for s in site.stations},
        {p.id: p.position_enu_m for p in site.pickets},
        site.picket_settings.bearing_error_deg,
    )


def start_pipeline(
    sensor_bus: Bus,
    ingest_bus: Bus,
    control_bus: Bus,
    site: SiteConfig,
    now: Callable[[], float],
) -> asyncio.Task[None]:
    """Subscribe now, before anything is published, then run until the sensor bus closes."""
    observations = sensor_bus.subscribe(WILDCARD)
    accepted = ingest_bus.subscribe(GATEWAY_ACCEPTED)
    gateway = Gateway(site.gateway, known_sensors(site), now)
    return asyncio.create_task(
        _run(
            gateway,
            observations,
            control_layer(site),
            accepted,
            ingest_bus,
            control_bus,
        )
    )


async def run_control(
    layer: ControlLayer, accepted: AsyncIterator[Message], sink: Bus
) -> None:
    """The control layer as a task: every accepted message in order, then the last batch."""
    async for message in accepted:
        for output in layer.ingest(message):
            await sink.publish(_topic(output), output)
    for output in layer.flush():
        await sink.publish(_topic(output), output)


async def _run(
    gateway: Gateway,
    observations: AsyncIterator[Message],
    layer: ControlLayer,
    accepted: AsyncIterator[Message],
    ingest_bus: Bus,
    control_bus: Bus,
) -> None:
    control = asyncio.create_task(run_control(layer, accepted, control_bus))
    await run_gateway(gateway, observations, ingest_bus)
    await ingest_bus.close()
    await control
    await control_bus.close()


def _topic(message: Message) -> str:
    return TRACK if isinstance(message, Track) else SECTOR_TRACK
