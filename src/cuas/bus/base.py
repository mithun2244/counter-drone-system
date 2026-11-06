"""The bus interface. Components depend on this, so a network bus can replace the in-process one."""

from collections.abc import AsyncIterator
from typing import Protocol

from cuas.schemas import Message

WILDCARD = "#"


class Bus(Protocol):
    async def publish(self, topic: str, msg: Message) -> None: ...

    def subscribe(self, topic: str) -> AsyncIterator[Message]:
        """Start receiving now. ``WILDCARD`` receives every topic, in exact publish order."""
        ...

    async def close(self) -> None:
        """End every subscription once its queued messages are read."""
        ...
