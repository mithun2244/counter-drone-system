import logging

import pytest

from cuas.bus import WILDCARD, InProcessBus
from cuas.config import SiteConfig
from cuas.gateway.gateway import Gateway, known_sensors, run_gateway
from cuas.schemas import (
    BearingDetection,
    Message,
    PicketAlert,
    RejectedMessage,
    SensorStatus,
)
from cuas.schemas.topics import GATEWAY_ACCEPTED, GATEWAY_REJECTED

NOW = 20.0


def bearing(**changes: object) -> BearingDetection:
    values = {
        "station_id": "st1",
        "sensor": "rgb",
        "t": NOW,
        "azimuth_deg": 135.0,
        "elevation_deg": 2.0,
        "sigma_deg": 0.05,
    }
    return BearingDetection(**{**values, **changes})


def gateway(site: SiteConfig, now: float = NOW) -> Gateway:
    return Gateway(site.gateway, known_sensors(site), lambda: now)


def admit(site: SiteConfig, message: Message, now: float = NOW):
    return gateway(site, now).admit(type(message).__name__, message.model_dump_json())


def reason(result: object) -> str:
    assert isinstance(result, RejectedMessage)
    return result.reason.split(":")[0]


@pytest.mark.parametrize(
    "message",
    [
        bearing(),
        PicketAlert(
            picket_id="pk4",
            t=NOW,
            bearing_deg=300.0,
            loudness=0.4,
            engine_type_probs={"piston": 0.8, "electric": 0.2},
        ),
        SensorStatus(sensor_id="st2.thermal", ok=True, visibility_factor=1.0, t=NOW),
        SensorStatus(sensor_id="pk8", ok=True, visibility_factor=0.9, t=NOW),
    ],
    ids=lambda m: type(m).__name__,
)
def test_a_valid_message_passes_unchanged(site: SiteConfig, message: Message) -> None:
    assert admit(site, message) == message


@pytest.mark.parametrize(
    ("kind", "raw"),
    [
        ("BearingDetection", "not json"),
        ("BearingDetection", bearing().model_dump_json().replace("135.0", "999.0")),
        (
            "BearingDetection",
            bearing().model_dump_json().replace("}", ', "target_id": "quad-1"}', 1),
        ),
        ("BearingDetection", bearing().model_dump_json().replace("0.05", "NaN")),
        ("Track", bearing().model_dump_json()),
    ],
    ids=["not json", "azimuth out of range", "extra field", "NaN", "wrong type"],
)
def test_a_malformed_message_is_rejected_as_schema(
    site: SiteConfig, kind: str, raw: str
) -> None:
    result = gateway(site).admit(kind, raw)
    assert reason(result) == "schema"
    assert result.raw == raw


def test_a_message_built_without_validation_is_still_checked(site: SiteConfig) -> None:
    unchecked = BearingDetection.model_construct(
        **{**bearing().model_dump(), "azimuth_deg": 999.0}
    )
    assert reason(admit(site, unchecked)) == "schema"


@pytest.mark.parametrize(
    ("t", "expected"),
    [
        (NOW + 2.0, None),
        (NOW + 2.25, "future"),
        (NOW - 10.0, None),
        (NOW - 10.25, "stale"),
    ],
)
def test_timestamps_are_checked_against_the_clock_at_the_exact_limits(
    site: SiteConfig, t: float, expected: str | None
) -> None:
    result = admit(site, bearing(t=t))
    if expected is None:
        assert result == bearing(t=t)
    else:
        assert reason(result) == expected


@pytest.mark.parametrize(
    "message",
    [
        bearing(station_id="st9"),
        PicketAlert(
            picket_id="pk9", t=NOW, bearing_deg=1.0, loudness=0.1, engine_type_probs={}
        ),
        SensorStatus(sensor_id="st1.radar", ok=True, visibility_factor=1.0, t=NOW),
    ],
    ids=["station", "picket", "status"],
)
def test_an_unknown_sensor_is_rejected(site: SiteConfig, message: Message) -> None:
    assert reason(admit(site, message)) == "unknown_sensor"


def test_a_rejection_is_logged(
    site: SiteConfig, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="cuas.gateway.gateway"):
        admit(site, bearing(station_id="st9"))
    assert "unknown_sensor: st9.rgb" in caplog.text


async def test_the_task_keeps_order_and_splits_accepted_from_rejected(
    site: SiteConfig,
) -> None:
    sensors, ingest = InProcessBus(), InProcessBus()
    source = sensors.subscribe(WILDCARD)
    accepted, rejected = (
        ingest.subscribe(GATEWAY_ACCEPTED),
        ingest.subscribe(GATEWAY_REJECTED),
    )
    messages = [
        bearing(azimuth_deg=1.0),
        bearing(station_id="st9"),
        bearing(azimuth_deg=2.0),
    ]
    for message in messages:
        await sensors.publish("station.bearing", message)
    await sensors.close()
    await run_gateway(gateway(site), source, ingest)
    await ingest.close()
    assert [m async for m in accepted] == [messages[0], messages[2]]
    assert [reason(m) async for m in rejected] == ["unknown_sensor"]


@pytest.mark.parametrize("scenario_id", ["s1", "s2", "s3", "s4", "s5"])
async def test_nothing_the_simulator_sends_is_rejected(
    record, site: SiteConfig, scenario_id: str
) -> None:
    messages, _ = await record(scenario_id, seed=7)
    assert messages
    for message in messages:
        assert admit(site, message, now=message.t) == message
