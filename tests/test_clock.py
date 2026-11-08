import asyncio
import time

import pytest

from cuas.clock import SimClock


async def test_starts_at_zero_and_advances_in_whole_ticks() -> None:
    clock = SimClock(0.2)
    assert clock.now == 0.0
    for _ in range(3):
        await clock.tick()
    assert clock.now == 3 * 0.2


async def test_reading_the_clock_does_not_advance_it() -> None:
    clock = SimClock(0.2)
    await clock.tick()
    first = clock.now
    await asyncio.sleep(0.01)
    assert clock.now == first


async def test_many_ticks_do_not_accumulate_float_error() -> None:
    clock = SimClock(0.2)
    summed = 0.0
    for _ in range(5000):
        await clock.tick()
        summed += 0.2
    assert clock.now == 5000 * 0.2
    assert summed != clock.now  # the error this design avoids


async def test_fast_mode_does_not_wait_for_the_wall_clock() -> None:
    clock = SimClock(10.0)
    start = time.perf_counter()
    for _ in range(1000):
        await clock.tick()
    assert time.perf_counter() - start < 1.0  # 10,000 simulated seconds


async def test_fast_mode_lets_other_tasks_run() -> None:
    clock = SimClock(0.2)
    seen: list[float] = []

    async def other() -> None:
        seen.append(clock.now)

    task = asyncio.create_task(other())
    await clock.tick()
    assert seen == [0.2]
    await task


@pytest.mark.parametrize(("pace", "low", "high"), [(1.0, 0.9, 2.0), (2.0, 0.45, 1.5)])
async def test_pace_holds_simulated_time_to_wall_time(
    pace: float, low: float, high: float
) -> None:
    clock = SimClock(0.2, pace=pace)
    start = time.perf_counter()
    for _ in range(5):  # 1 simulated second
        await clock.tick()
    assert low <= time.perf_counter() - start <= high
    assert clock.now == 5 * 0.2


async def test_work_before_the_first_tick_is_caught_up_once_started() -> None:
    clock = SimClock(0.2, pace=2.0)  # one tick is 0.1 s of wall time
    clock.start()
    await asyncio.sleep(0.1)  # the first tick's work
    started = time.perf_counter()
    await clock.tick()
    assert time.perf_counter() - started < 0.05
    assert clock.now == 0.2


async def test_pause_holds_the_next_tick_until_resume() -> None:
    clock = SimClock(0.2, pace=2.0)  # one tick is 0.1 s of wall time
    clock.start()
    await clock.tick()
    clock.pause()
    assert clock.paused

    async def two_ticks() -> None:
        await clock.tick()
        await clock.tick()

    task = asyncio.create_task(two_ticks())
    await asyncio.sleep(0.3)
    assert not task.done()
    assert clock.now == pytest.approx(0.4)  # counted, but held
    started = time.perf_counter()
    clock.resume()
    await task
    # The held tick returns at once; the next waits its own 0.1 s, with no race to catch up.
    assert 0.08 <= time.perf_counter() - started <= 0.5
    assert clock.now == pytest.approx(0.6)


async def test_a_new_pace_applies_from_now_on() -> None:
    clock = SimClock(0.2, pace=1.0)
    clock.start()
    await clock.tick()
    clock.set_pace(5.0)  # one tick is now 0.04 s
    started = time.perf_counter()
    for _ in range(5):
        await clock.tick()
    assert 0.15 <= time.perf_counter() - started <= 0.6
    assert clock.pace == 5.0


def test_a_fast_clock_has_no_pace_to_change() -> None:
    with pytest.raises(ValueError):
        SimClock(0.2).set_pace(2.0)


async def test_a_pace_must_be_positive() -> None:
    clock = SimClock(0.2, pace=1.0)
    with pytest.raises(ValueError):
        clock.set_pace(0.0)


@pytest.mark.parametrize(
    "kwargs", [{"tick_s": 0.0}, {"tick_s": -1.0}, {"tick_s": 0.2, "pace": 0.0}]
)
def test_bad_settings_are_rejected(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        SimClock(**kwargs)
