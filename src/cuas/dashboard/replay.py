"""Plays a recorded contract stream through the real server, for building the UI without a run.

It serves the profiles from the file's ``hello``, starts only the run the file holds, and paces
its frames and evidence events by their simulated time on the same clock a live run uses, so
pause and speed work. The run ends when the file does. Recordings are served if the file sits
next to a folder named after its run, as ``scripts/record_stream.py --recorded-media`` leaves it.
"""

import asyncio
from pathlib import Path

from pydantic import TypeAdapter

from cuas.clock import SimClock
from cuas.dashboard.contract import (
    EvidenceEvent,
    Frame,
    Hello,
    RunInfo,
    ServerMessage,
    SiteProfile,
    StartRun,
)
from cuas.dashboard.server import Publish, Started

EARLY = 1e-9
REAL_TIME = 1.0


class ReplayLauncher:
    def __init__(self, path: Path, tick_s: float, pace: float = REAL_TIME) -> None:
        adapter = TypeAdapter(ServerMessage)
        lines = path.read_text(encoding="utf-8").splitlines()
        messages = [adapter.validate_json(line) for line in lines if line.strip()]
        hellos = [m for m in messages if isinstance(m, Hello)]
        runs = [m for m in messages if isinstance(m, RunInfo)]
        if not runs:
            raise ValueError(f"{path} holds no run")
        self._profiles = hellos[0].profiles if hellos else []
        self._run = runs[0].model_copy(update={"state": "running", "speed": 1.0})
        self._played = [m for m in messages if isinstance(m, Frame | EvidenceEvent)]
        clips = path.parent / self._run.run_id
        self._clips_dir = clips if clips.is_dir() else None
        self._tick_s = tick_s
        self._pace = pace

    def profiles(self) -> list[SiteProfile]:
        return self._profiles

    async def start(self, request: StartRun, publish: Publish) -> Started:
        run = self._run
        if (request.profile_id, request.scenario_id) != (
            run.profile_id,
            run.scenario_id,
        ):
            raise LookupError(
                f"this replay holds {run.scenario_id} at {run.profile_id} only"
            )
        clock = SimClock(self._tick_s, pace=self._pace)
        done = asyncio.create_task(self._play(clock, publish))
        return Started(run, clock, self._pace, self._clips_dir, done)

    async def _play(self, clock: SimClock, publish: Publish) -> None:
        clock.start()
        for message in self._played:
            while clock.now + EARLY < message.t:
                await clock.tick()
                if clock.stopped:
                    return
            publish(message)
