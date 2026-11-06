"""The single simulated clock. Pipeline code reads time from here, never from the wall."""

import asyncio


class SimClock:
    """Advances in whole ticks, so ``now`` never accumulates float error.

    ``pace`` is simulated seconds per wall second: ``None`` runs as fast as possible, and 1.0 is
    real time. Pacing only decides when ``tick`` returns; it cannot change ``now``.
    """

    def __init__(self, tick_s: float, pace: float | None = None) -> None:
        if tick_s <= 0:
            raise ValueError(f"tick_s must be positive, got {tick_s}")
        if pace is not None and pace <= 0:
            raise ValueError(f"pace must be positive or None, got {pace}")
        self.tick_s = tick_s
        self._pace = pace
        self._ticks = 0
        self._wall_start: float | None = None

    @property
    def now(self) -> float:
        return self._ticks * self.tick_s

    async def tick(self) -> None:
        """Advance one tick and let other tasks run, holding the pace if one is set."""
        self._ticks += 1
        if self._pace is None:
            await asyncio.sleep(0)
            return
        loop = asyncio.get_running_loop()
        if self._wall_start is None:
            self._wall_start = loop.time()
        # Sleep to a deadline, not for a fixed time, so timer overshoot does not build up.
        deadline = self._wall_start + self.now / self._pace
        await asyncio.sleep(max(0.0, deadline - loop.time()))
