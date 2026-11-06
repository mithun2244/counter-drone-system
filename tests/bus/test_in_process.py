from dataclasses import dataclass

import pytest

from cuas.bus import WILDCARD, InProcessBus
from cuas.schemas import RejectedMessage


def msg(n: int) -> RejectedMessage:
    return RejectedMessage(reason=str(n), raw="")


async def read_all(
    bus: InProcessBus, *subscriptions: object
) -> list[list[RejectedMessage]]:
    await bus.close()
    return [[m async for m in sub] for sub in subscriptions]  # type: ignore[attr-defined]


async def test_subscriber_receives_messages_in_publish_order() -> None:
    bus = InProcessBus()
    sub = bus.subscribe("a")
    for n in range(5):
        await bus.publish("a", msg(n))
    assert await read_all(bus, sub) == [[msg(n) for n in range(5)]]


async def test_every_subscriber_gets_its_own_copy() -> None:
    bus = InProcessBus()
    first, second = bus.subscribe("a"), bus.subscribe("a")
    await bus.publish("a", msg(1))
    assert await read_all(bus, first, second) == [[msg(1)], [msg(1)]]


async def test_topics_are_kept_apart() -> None:
    bus = InProcessBus()
    a, b = bus.subscribe("a"), bus.subscribe("b")
    await bus.publish("a", msg(1))
    await bus.publish("b", msg(2))
    assert await read_all(bus, a, b) == [[msg(1)], [msg(2)]]


async def test_wildcard_sees_all_topics_in_exact_publish_order() -> None:
    bus = InProcessBus()
    tap = bus.subscribe(WILDCARD)
    for n, topic in enumerate(["a", "b", "a", "c", "b"]):
        await bus.publish(topic, msg(n))
    assert await read_all(bus, tap) == [[msg(n) for n in range(5)]]


async def test_subscription_starts_when_subscribe_is_called_not_at_first_read() -> None:
    bus = InProcessBus()
    await bus.publish("a", msg(0))
    sub = bus.subscribe("a")
    await bus.publish("a", msg(1))
    assert await read_all(bus, sub) == [[msg(1)]]


async def test_publishing_with_no_subscribers_is_fine() -> None:
    await InProcessBus().publish("a", msg(1))


async def test_only_message_types_can_be_published() -> None:
    @dataclass
    class NotAMessage:
        target_id: str

    with pytest.raises(TypeError):
        await InProcessBus().publish("a", NotAMessage("quad-1"))  # type: ignore[arg-type]


async def test_nobody_can_publish_to_the_wildcard() -> None:
    with pytest.raises(ValueError):
        await InProcessBus().publish(WILDCARD, msg(1))


async def test_publishing_after_close_fails() -> None:
    bus = InProcessBus()
    await bus.close()
    with pytest.raises(RuntimeError):
        await bus.publish("a", msg(1))


async def test_subscribing_after_close_ends_at_once() -> None:
    bus = InProcessBus()
    await bus.close()
    assert [m async for m in bus.subscribe("a")] == []
