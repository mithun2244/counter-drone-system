"""The single simulated clock. Pipeline code reads time from here, never from the wall."""

import asyncio


class SimClock:
    """Advances in whole ticks, so ``now`` never accumulates float error.

    ``pace`` is simulated seconds per wall second: ``None`` runs as fast as possible, and 1.0 is
    real time. Pacing, pausing and speed changes only decide when ``tick`` returns; they cannot
    change ``now``.
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
        self._running = asyncio.Event()
        self._running.set()

    @property
    def now(self) -> float:
        return self._ticks * self.tick_s

    @property
    def pace(self) -> float | None:
        return self._pace

    @property
    def paused(self) -> bool:
        return not self._running.is_set()

    def pause(self) -> None:
        """Hold the next ``tick`` until ``resume``: simulated time stops, nothing else changes."""
        self._running.clear()

    def resume(self) -> None:
        self._rebase()
        self._running.set()

    def set_pace(self, pace: float) -> None:
        """Run at a new speed from the current simulated time on."""
        if self._pace is None:
            raise ValueError(
                "a clock running as fast as possible has no pace to change"
            )
        if pace <= 0:
            raise ValueError(f"pace must be positive, got {pace}")
        self._pace = pace
        self._rebase()

    def _rebase(self) -> None:
        """Make now on the wall clock line up with ``now``, so a pause or speed change is not
        followed by a race to catch up."""
        if self._pace is not None and self._wall_start is not None:
            loop = asyncio.get_running_loop()
            self._wall_start = loop.time() - self.now / self._pace

    def start(self) -> None:
        """Pace from this moment, so the work of the first tick is caught up like any other.

        Without it, pacing starts at the first ``tick`` and the first tick's work adds to the run.
        """
        if self._pace is not None:
            self._wall_start = asyncio.get_running_loop().time()

    async def tick(self) -> None:
        """Advance one tick and let other tasks run, holding the pace if one is set."""
        self._ticks += 1
        await self._running.wait()
        if self._pace is None:
            await asyncio.sleep(0)
            return
        loop = asyncio.get_running_loop()
        if self._wall_start is None:
            self._wall_start = loop.time()
        # Sleep to a deadline, not for a fixed time, so timer overshoot does not build up.
        deadline = self._wall_start + self.now / self._pace
        await asyncio.sleep(max(0.0, deadline - loop.time()))
