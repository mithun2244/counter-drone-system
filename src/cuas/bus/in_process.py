"""In-process bus built on ``asyncio.Queue``."""

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator

from cuas.bus.base import WILDCARD
from cuas.schemas import Message

_CLOSED = object()


class InProcessBus:
    # ponytail: unbounded queues, so a stalled subscriber grows memory; bounded queues with a drop
    # policy when a network bus arrives.
    def __init__(self) -> None:
        self._queues: defaultdict[str, list[asyncio.Queue[object]]] = defaultdict(list)
        self._closed = False

    async def publish(self, topic: str, msg: Message) -> None:
        if not isinstance(msg, Message):
            raise TypeError(
                f"only Message types go on the bus, got {type(msg).__name__}"
            )
        if topic == WILDCARD:
            raise ValueError(f"{WILDCARD!r} is for subscribing, not publishing")
        if self._closed:
            raise RuntimeError("bus is closed")
        for queue in self._queues[topic] + self._queues[WILDCARD]:
            queue.put_nowait(msg)

    def subscribe(self, topic: str) -> AsyncIterator[Message]:
        # A plain function, so the subscription starts here and not at the first read.
        queue: asyncio.Queue[object] = asyncio.Queue()
        self._queues[topic].append(queue)
        if self._closed:
            queue.put_nowait(_CLOSED)
        return _read(queue)

    async def close(self) -> None:
        self._closed = True
        for queues in self._queues.values():
            for queue in queues:
                queue.put_nowait(_CLOSED)


async def _read(queue: asyncio.Queue[object]) -> AsyncIterator[Message]:
    while (item := await queue.get()) is not _CLOSED:
        yield item  # type: ignore[misc]
