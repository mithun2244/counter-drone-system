"""The mast-bias wrapper turns one station's bearings and nothing else."""

import pytest

from cuas.bus import WILDCARD, InProcessBus
from cuas.schemas import BearingDetection, SensorStatus
from cuas.sim.bias import MastBias


def bearing(station_id: str, azimuth_deg: float) -> BearingDetection:
    return BearingDetection(
        station_id=station_id,
        sensor="rgb",
        t=1.0,
        azimuth_deg=azimuth_deg,
        elevation_deg=5.0,
        sigma_deg=0.05,
    )


async def test_only_the_biased_station_is_turned_and_azimuth_wraps() -> None:
    bus = InProcessBus()
    tap = bus.subscribe(WILDCARD)
    biased = MastBias(bus, "st1", 0.5)
    status = SensorStatus(sensor_id="st1.rgb", ok=True, visibility_factor=1.0, t=1.0)
    for msg in (bearing("st1", 359.8), bearing("st2", 10.0), status):
        await biased.publish("topic", msg)
    await biased.close()
    first, second, third = [m async for m in tap]
    assert first.azimuth_deg == pytest.approx(0.3)
    assert second == bearing("st2", 10.0)
    assert third == status
