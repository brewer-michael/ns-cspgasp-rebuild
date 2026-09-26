"""Timers and alarms: counting down, ringing, restarts, missed alarms and the state file."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from conftest import wait_for

from open_speaker.intents import EVERY_DAY, TOMORROW, WEEKDAYS, WEEKENDS
from open_speaker.timers import Alarm, Ring, Scheduler, next_occurrence

Restart = Callable[..., Awaitable[Scheduler]]

JULY_15 = datetime(2026, 7, 15)  # a Wednesday, far from any daylight saving change
MONDAY, WEDNESDAY, FRIDAY = 0, 2, 4


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """Local time ``day`` days after Wednesday 15 July 2026."""
    return JULY_15 + timedelta(days=day, hours=hour, minutes=minute)


def when(alarm: Alarm) -> datetime:
    return datetime.fromtimestamp(alarm.next_at)


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start.timestamp()

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def set(self, moment: datetime) -> None:
        self.now = moment.timestamp()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(at(0, 8))  # Wednesday 08:00


@pytest.fixture
def rings() -> list[Ring]:
    return []


@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    return tmp_path / "state" / "timers.json"


@pytest.fixture
def new_scheduler(
    state_file: Path, clock: FakeClock, rings: list[Ring]
) -> Callable[..., Scheduler]:
    def new(grace: float = 600.0) -> Scheduler:
        async def on_ring(ring: Ring) -> None:
            rings.append(ring)

        return Scheduler(state_file, on_ring, missed_grace_seconds=grace, clock=clock)

    return new


@pytest.fixture
def scheduler(new_scheduler: Callable[..., Scheduler]) -> Scheduler:
    return new_scheduler()


@pytest.fixture
async def restart(
    new_scheduler: Callable[..., Scheduler],
) -> AsyncIterator[Restart]:
    """Start a new Scheduler on the same state file, as after a reboot."""
    started: list[Scheduler] = []

    async def restart(grace: float = 600.0) -> Scheduler:
        scheduler = new_scheduler(grace)
        await scheduler.start()
        started.append(scheduler)
        return scheduler

    yield restart
    for scheduler in started:
        await scheduler.stop()


# ---------------------------------------------------------------------------
# Timers


def test_timer_counts_down(scheduler: Scheduler, clock: FakeClock) -> None:
    timer = scheduler.add_timer(300, "tea")
    assert scheduler.timers() == [timer]
    assert (timer.seconds, timer.name, timer.kind) == (300, "tea", "timer")
    assert timer.label == "tea timer"
    assert scheduler.remaining(timer) == 300
    clock.advance(120)
    assert scheduler.remaining(timer) == 180
    clock.advance(1000)
    assert scheduler.remaining(timer) == 0


def test_timers_are_listed_by_end_time(scheduler: Scheduler, clock: FakeClock) -> None:
    pizza = scheduler.add_timer(600, "pizza")
    clock.advance(10)
    plain = scheduler.add_timer(60)
    assert scheduler.timers() == [plain, pizza]
    assert plain.label == "timer"
    assert plain.id != pizza.id


def test_find_timers_by_name(scheduler: Scheduler) -> None:
    tea = scheduler.add_timer(180, "tea")
    green_tea = scheduler.add_timer(120, "green tea")
    pizza = scheduler.add_timer(600, "pizza")
    plain = scheduler.add_timer(60)
    assert scheduler.find_timers("tea") == [green_tea, tea]
    assert scheduler.find_timers("pizza") == [pizza]
    assert scheduler.find_timers("soup") == []
    assert scheduler.find_timers(None) == [plain, green_tea, tea, pizza]


def test_find_timers_by_length(scheduler: Scheduler) -> None:
    five = scheduler.add_timer(300)
    tea = scheduler.add_timer(180, "tea")
    also_five = scheduler.add_timer(300, "eggs")
    # "cancel the 5 minute timer": no timer has that name, so match the length
    assert scheduler.find_timers("5 minute") == [five, also_five]
    assert scheduler.find_timers("three minute") == [tea]
    assert scheduler.find_timers("10 minute") == []
    assert scheduler.cancel_timers("five minute") == [five, also_five]
    assert scheduler.timers() == [tea]


def test_cancel_without_a_name_cancels_the_timer_ending_first(scheduler: Scheduler) -> None:
    long = scheduler.add_timer(600)
    short = scheduler.add_timer(60)
    assert scheduler.cancel_timers() == [short]
    assert scheduler.timers() == [long]


def test_cancel_by_name_cancels_every_match(scheduler: Scheduler) -> None:
    tea = scheduler.add_timer(180, "tea")
    green_tea = scheduler.add_timer(120, "green tea")
    pizza = scheduler.add_timer(600, "pizza")
    assert scheduler.cancel_timers("soup") == []
    assert scheduler.cancel_timers("tea") == [green_tea, tea]
    assert scheduler.timers() == [pizza]


async def test_cancel_all_timers_keeps_a_snoozed_alarm(
    scheduler: Scheduler, clock: FakeClock, rings: list[Ring]
) -> None:
    scheduler.add_timer(60)
    scheduler.add_timer(120, "tea")
    snoozed = scheduler.snooze(9)
    assert len(scheduler.cancel_timers(all=True)) == 2
    assert scheduler.timers() == []
    clock.advance(9 * 60)
    await scheduler.check()
    assert rings == [Ring("alarm", "alarm", snoozed.id)]


async def test_timer_rings_once_when_it_ends(
    scheduler: Scheduler, clock: FakeClock, rings: list[Ring]
) -> None:
    timer = scheduler.add_timer(300, "tea")
    clock.advance(299)
    await scheduler.check()
    assert rings == []
    clock.advance(1)
    await scheduler.check()
    assert rings == [Ring("timer", "tea timer", timer.id)]
    assert scheduler.timers() == []
    await scheduler.check()
    assert len(rings) == 1


async def test_a_failing_ring_handler_does_not_silence_the_others(
    state_file: Path, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    heard: list[str] = []

    async def on_ring(ring: Ring) -> None:
        heard.append(ring.label)
        if len(heard) == 1:
            raise RuntimeError("speaker unplugged")

    scheduler = Scheduler(state_file, on_ring, clock=clock)
    scheduler.add_timer(10, "egg")
    scheduler.add_timer(20, "tea")
    clock.advance(30)
    await scheduler.check()
    assert heard == ["egg timer", "tea timer"]
    assert "Error while ringing egg timer" in caplog.text


async def test_the_run_loop_wakes_up_for_a_new_timer(tmp_path: Path) -> None:
    rings: list[Ring] = []

    async def on_ring(ring: Ring) -> None:
        rings.append(ring)

    scheduler = Scheduler(tmp_path / "timers.json", on_ring)  # the real clock
    await scheduler.start()
    try:
        await asyncio.sleep(0.01)  # nothing is scheduled, so the loop is asleep
        started = time.monotonic()
        timer = scheduler.add_timer(0.05, "egg")
        await wait_for(lambda: bool(rings), timeout=1.0)
        assert time.monotonic() - started >= 0.04
    finally:
        await scheduler.stop()
    await scheduler.stop()  # stopping twice is harmless
    assert rings == [Ring("timer", "egg timer", timer.id)]


# ---------------------------------------------------------------------------
# Alarms


@pytest.mark.parametrize(
    ("after", "hour", "minute", "repeat", "day", "expected"),
    [
        (at(0, 6), 7, 0, frozenset(), None, at(0, 7)),
        (at(0, 7) - timedelta(seconds=1), 7, 0, frozenset(), None, at(0, 7)),
        (at(0, 7), 7, 0, frozenset(), None, at(1, 7)),  # strictly after
        (at(0, 8), 7, 0, frozenset(), None, at(1, 7)),
        (at(0, 8), 0, 0, frozenset(), None, at(1, 0)),
        (at(0, 8), 7, 30, WEEKDAYS, None, at(1, 7, 30)),
        (at(2, 8), 7, 0, WEEKDAYS, None, at(5, 7)),  # Friday -> Monday
        (at(0, 8), 9, 0, WEEKENDS, None, at(3, 9)),  # Wednesday -> Saturday
        (at(3, 10), 9, 0, WEEKENDS, None, at(4, 9)),  # Saturday -> Sunday
        (at(4, 10), 9, 0, WEEKENDS, None, at(10, 9)),  # Sunday -> next Saturday
        (at(0, 6), 7, 0, EVERY_DAY, None, at(0, 7)),
        (at(0, 8), 7, 0, frozenset({MONDAY}), None, at(5, 7)),
        (at(0, 6), 7, 0, frozenset(), TOMORROW, at(1, 7)),  # not later today
        (at(0, 23, 30), 7, 0, frozenset(), TOMORROW, at(1, 7)),
        (at(0, 8), 7, 0, frozenset(), FRIDAY, at(2, 7)),
        (at(0, 6), 7, 0, frozenset(), WEDNESDAY, at(0, 7)),  # today, still ahead
        (at(0, 8), 7, 0, frozenset(), WEDNESDAY, at(7, 7)),  # today has passed
        (datetime(2026, 7, 31, 8), 7, 0, WEEKDAYS, None, datetime(2026, 8, 3, 7)),
        (datetime(2026, 12, 31, 23), 7, 0, frozenset(), None, datetime(2027, 1, 1, 7)),
    ],
)
def test_next_occurrence(
    after: datetime,
    hour: int,
    minute: int,
    repeat: frozenset[int],
    day: int | None,
    expected: datetime,
) -> None:
    assert next_occurrence(hour, minute, after, repeat, day) == expected


def test_add_alarm(scheduler: Scheduler) -> None:
    tomorrow = scheduler.add_alarm(7, 30)
    later_today = scheduler.add_alarm(9, 0)
    assert when(later_today) == at(0, 9)
    assert when(tomorrow) == at(1, 7, 30)
    assert (tomorrow.hour, tomorrow.minute, tomorrow.repeat, tomorrow.enabled) == (7, 30, [], True)
    assert scheduler.alarms() == [later_today, tomorrow]
    assert scheduler.next_alarm() == later_today


def test_no_alarms(scheduler: Scheduler) -> None:
    assert scheduler.alarms() == []
    assert scheduler.next_alarm() is None
    assert scheduler.cancel_alarms() == []


@pytest.mark.parametrize(
    ("now", "hour", "minute", "ambiguous", "expected"),
    [
        (at(0, 6), 7, 0, True, at(0, 7)),  # 7:00 comes before 19:00
        (at(0, 8), 7, 0, True, at(0, 19)),  # 7:00 has passed, 19:00 has not
        (at(0, 20), 7, 0, True, at(1, 7)),  # both passed: 7:00 tomorrow
        (at(0, 8), 7, 30, True, at(0, 19, 30)),
        (at(0, 8), 0, 0, True, at(0, 12)),  # "12" is noon or midnight
        (at(0, 13), 0, 0, True, at(1, 0)),
        (at(0, 8), 7, 0, False, at(1, 7)),  # "7 am" is never 19:00
        (at(0, 8), 19, 0, True, at(0, 19)),
    ],
)
def test_an_ambiguous_hour_picks_the_earlier_of_h_and_h_plus_12(
    scheduler: Scheduler,
    clock: FakeClock,
    now: datetime,
    hour: int,
    minute: int,
    ambiguous: bool,
    expected: datetime,
) -> None:
    clock.set(now)
    alarm = scheduler.add_alarm(hour, minute, ambiguous=ambiguous)
    assert when(alarm) == expected
    assert (alarm.hour, alarm.minute) == (expected.hour, expected.minute)


def test_an_ambiguous_repeating_alarm(scheduler: Scheduler, clock: FakeClock) -> None:
    clock.set(at(3, 8))  # Saturday
    alarm = scheduler.add_alarm(7, 0, WEEKDAYS, ambiguous=True)
    assert when(alarm) == at(5, 7)


def test_a_repeating_alarm(scheduler: Scheduler, clock: FakeClock) -> None:
    clock.set(at(2, 8))  # Friday
    alarm = scheduler.add_alarm(7, 0, WEEKDAYS)
    assert alarm.repeat == [0, 1, 2, 3, 4]
    assert when(alarm) == at(5, 7)
    assert alarm.describe() == "7 AM on weekdays"
    assert alarm.describe(clock_24h=True) == "07:00 on weekdays"


def test_an_alarm_for_tomorrow_skips_later_today(scheduler: Scheduler, clock: FakeClock) -> None:
    clock.set(at(0, 6))
    alarm = scheduler.add_alarm(7, 0, day=TOMORROW)
    assert when(alarm) == at(1, 7)
    assert alarm.repeat == []
    assert alarm.describe() == "7 AM"


def test_an_alarm_on_a_given_day(scheduler: Scheduler) -> None:
    friday = scheduler.add_alarm(7, 0, day=FRIDAY)
    wednesday = scheduler.add_alarm(7, 0, day=WEDNESDAY)
    assert when(friday) == at(2, 7)
    assert when(wednesday) == at(7, 7)
    assert friday.repeat == []


def test_describe_an_alarm() -> None:
    assert Alarm("a", 6, 30, [MONDAY, WEDNESDAY]).describe() == (
        "6:30 AM every Monday and Wednesday"
    )
    assert Alarm("b", 19, 5, list(EVERY_DAY)).describe(clock_24h=True) == "19:05 every day"
    assert Alarm("c", 0, 0).label == "alarm"


async def test_a_one_off_alarm_rings_once(
    scheduler: Scheduler, clock: FakeClock, rings: list[Ring]
) -> None:
    alarm = scheduler.add_alarm(9, 0)
    clock.set(at(0, 8, 59))
    await scheduler.check()
    assert rings == []
    clock.set(at(0, 9))
    await scheduler.check()
    assert rings == [Ring("alarm", "alarm", alarm.id)]
    assert scheduler.alarms() == []


async def test_a_repeating_alarm_moves_on_to_its_next_day(
    scheduler: Scheduler, clock: FakeClock, rings: list[Ring]
) -> None:
    alarm = scheduler.add_alarm(7, 0, WEEKDAYS)
    assert when(alarm) == at(1, 7)  # Thursday
    for next_time in (at(2, 7), at(5, 7)):  # Friday, then Monday
        clock.now = alarm.next_at
        await scheduler.check()
        assert when(alarm) == next_time
    assert rings == [Ring("alarm", "alarm", alarm.id)] * 2
    assert scheduler.alarms() == [alarm]


@pytest.fixture
def three_alarms(scheduler: Scheduler) -> tuple[Alarm, Alarm, Alarm]:
    """It is Wednesday 08:00: alarms at 19:00 today, and at 7:00 and 7:30 tomorrow."""
    return scheduler.add_alarm(19, 0), scheduler.add_alarm(7, 0), scheduler.add_alarm(7, 30)


def test_cancel_the_next_alarm(scheduler: Scheduler, three_alarms: tuple[Alarm, ...]) -> None:
    evening, seven, half_past = three_alarms
    assert scheduler.cancel_alarms() == [evening]
    assert scheduler.alarms() == [seven, half_past]


def test_cancel_an_alarm_by_time(scheduler: Scheduler, three_alarms: tuple[Alarm, ...]) -> None:
    evening, seven, half_past = three_alarms
    assert scheduler.cancel_alarms(8, 0) == []
    assert scheduler.cancel_alarms(7) == [seven]  # the minute defaults to 0
    assert scheduler.cancel_alarms(7, 30) == [half_past]
    assert scheduler.alarms() == [evening]


def test_cancel_an_alarm_by_ambiguous_time(
    scheduler: Scheduler, three_alarms: tuple[Alarm, ...]
) -> None:
    evening, seven, half_past = three_alarms
    assert scheduler.cancel_alarms(7, 0, ambiguous=True) == [evening, seven]
    assert scheduler.alarms() == [half_past]


def test_cancel_all_alarms(scheduler: Scheduler, three_alarms: tuple[Alarm, ...]) -> None:
    assert scheduler.cancel_alarms(all=True) == list(three_alarms)
    assert scheduler.alarms() == []


async def test_snooze_rings_as_an_alarm(
    scheduler: Scheduler, clock: FakeClock, rings: list[Ring]
) -> None:
    snoozed = scheduler.snooze(9)
    assert (snoozed.kind, snoozed.label, snoozed.seconds) == ("snooze", "alarm", 540)
    assert scheduler.timers() == []  # not one of the user's timers
    clock.advance(9 * 60 - 1)
    await scheduler.check()
    assert rings == []
    clock.advance(1)
    await scheduler.check()
    assert rings == [Ring("alarm", "alarm", snoozed.id)]


# ---------------------------------------------------------------------------
# Restarts and missed alarms


async def test_timers_and_alarms_survive_a_restart(
    scheduler: Scheduler, clock: FakeClock, rings: list[Ring], restart: Restart
) -> None:
    tea = scheduler.add_timer(300, "tea")
    snoozed = scheduler.snooze(9)
    weekdays = scheduler.add_alarm(6, 30, WEEKDAYS)
    tomorrow = scheduler.add_alarm(7, 0, day=TOMORROW)
    restarted = await restart()
    assert restarted.timers() == [tea]
    assert restarted.remaining(restarted.timers()[0]) == 300
    assert restarted.alarms() == [weekdays, tomorrow]
    clock.advance(9 * 60)
    await restarted.check()
    assert rings == [Ring("timer", "tea timer", tea.id), Ring("alarm", "alarm", snoozed.id)]


async def test_changes_are_saved_straight_away(
    scheduler: Scheduler, clock: FakeClock, restart: Restart
) -> None:
    scheduler.add_timer(60)
    kept = scheduler.add_timer(600)
    scheduler.cancel_timers()
    scheduler.add_alarm(8, 5)
    clock.set(at(0, 8, 5))
    await scheduler.check()  # the alarm rang and is gone
    restarted = await restart()
    assert restarted.timers() == [kept]
    assert restarted.alarms() == []


async def test_starting_without_a_state_file(
    restart: Restart, state_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    scheduler = await restart()
    assert scheduler.timers() == []
    assert scheduler.alarms() == []
    assert not state_file.exists()
    assert "starting without timers" not in caplog.text


async def test_a_timer_that_ended_while_off_rings_within_the_grace_period(
    scheduler: Scheduler, clock: FakeClock, rings: list[Ring], restart: Restart
) -> None:
    timer = scheduler.add_timer(60, "tea")
    clock.advance(60 + 300)
    restarted = await restart()
    assert restarted.timers() == [timer]
    await restarted.check()
    assert rings == [Ring("timer", "tea timer", timer.id)]


async def test_a_timer_missed_by_more_than_the_grace_period_is_dropped(
    scheduler: Scheduler, clock: FakeClock, rings: list[Ring], restart: Restart, state_file: Path
) -> None:
    scheduler.add_timer(60, "tea")
    clock.advance(60 + 700)
    restarted = await restart()
    await restarted.check()
    assert restarted.timers() == []
    assert rings == []
    assert json.loads(state_file.read_text(encoding="utf-8"))["timers"] == []


async def test_the_grace_period_is_configurable(
    scheduler: Scheduler, clock: FakeClock, rings: list[Ring], restart: Restart
) -> None:
    scheduler.add_timer(60)
    clock.advance(60 + 120)
    restarted = await restart(grace=60)
    await restarted.check()
    assert restarted.timers() == []
    assert rings == []


async def test_an_alarm_missed_within_the_grace_period_rings_late(
    scheduler: Scheduler, clock: FakeClock, rings: list[Ring], restart: Restart
) -> None:
    clock.set(at(0, 6))
    alarm = scheduler.add_alarm(7, 0)
    clock.set(at(0, 7, 5))  # the speaker was off at 7:00
    restarted = await restart()
    await restarted.check()
    assert rings == [Ring("alarm", "alarm", alarm.id)]
    assert restarted.alarms() == []


async def test_an_alarm_missed_by_more_than_the_grace_period_is_dropped(
    scheduler: Scheduler, clock: FakeClock, rings: list[Ring], restart: Restart, state_file: Path
) -> None:
    clock.set(at(0, 6))
    scheduler.add_alarm(7, 0)
    clock.set(at(0, 7, 20))
    restarted = await restart()
    await restarted.check()
    assert rings == []
    assert restarted.alarms() == []
    assert json.loads(state_file.read_text(encoding="utf-8"))["alarms"] == []


async def test_a_long_missed_repeating_alarm_waits_for_its_next_day(
    scheduler: Scheduler, clock: FakeClock, rings: list[Ring], restart: Restart
) -> None:
    clock.set(at(0, 6))
    alarm = scheduler.add_alarm(7, 0, WEEKDAYS)
    clock.set(at(0, 7, 20))
    restarted = await restart()
    await restarted.check()
    assert rings == []
    [reloaded] = restarted.alarms()
    assert reloaded.id == alarm.id
    assert when(reloaded) == at(1, 7)


async def test_a_recently_missed_repeating_alarm_rings_then_moves_on(
    scheduler: Scheduler, clock: FakeClock, rings: list[Ring], restart: Restart
) -> None:
    clock.set(at(0, 6))
    alarm = scheduler.add_alarm(7, 0, WEEKDAYS)
    clock.set(at(0, 7, 5))
    restarted = await restart()
    await restarted.check()
    assert rings == [Ring("alarm", "alarm", alarm.id)]
    next_alarm = restarted.next_alarm()
    assert next_alarm is not None
    assert when(next_alarm) == at(1, 7)


# ---------------------------------------------------------------------------
# The state file


def test_state_file_format(scheduler: Scheduler, state_file: Path) -> None:
    timer = scheduler.add_timer(300, "tea")
    alarm = scheduler.add_alarm(6, 30, WEEKDAYS)
    assert json.loads(state_file.read_text(encoding="utf-8")) == {
        "timers": [
            {
                "id": timer.id,
                "seconds": 300,
                "ends_at": timer.ends_at,
                "name": "tea",
                "kind": "timer",
            },
        ],
        "alarms": [
            {
                "id": alarm.id,
                "hour": 6,
                "minute": 30,
                "repeat": [0, 1, 2, 3, 4],
                "next_at": alarm.next_at,
                "enabled": True,
            },
        ],
    }


def test_state_is_replaced_atomically(
    scheduler: Scheduler, state_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replaced: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def spy(src: str | Path, dst: str | Path) -> None:
        replaced.append((Path(src), Path(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    scheduler.add_timer(300)
    [(src, dst)] = replaced
    assert dst == state_file
    assert src != state_file
    assert src.parent == state_file.parent  # a rename within one filesystem
    assert list(state_file.parent.iterdir()) == [state_file]


def test_a_failed_save_keeps_the_previous_state(
    scheduler: Scheduler,
    state_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    scheduler.add_timer(300, "tea")
    saved = state_file.read_text(encoding="utf-8")

    def disk_full(src: str | Path, dst: str | Path) -> None:
        raise OSError("No space left on device")

    monkeypatch.setattr(os, "replace", disk_full)
    pizza = scheduler.add_timer(600, "pizza")
    assert state_file.read_text(encoding="utf-8") == saved
    assert pizza in scheduler.timers()
    assert "Could not save timers" in caplog.text


@pytest.mark.parametrize(
    "content",
    [
        b'{"timers": [{"id": "a1", "seconds": 6',
        b"",
        b"\x00\xff\xfe\x00",
        b"null",
        b"[]",
        b'{"timers": 5}',
        b'{"timers": [{"id": "a1", "seconds": 60, "ends_at": 0, "colour": "red"}]}',
        b'{"alarms": [{"id": "a1", "hour": 7}]}',
        b'{"timers": [{"id": "a1", "seconds": 60, "ends_at": null}]}',
        b'{"alarms": [{"id": "a1", "hour": 25, "minute": 0, "repeat": [0], "next_at": 0}]}',
    ],
    ids=[
        "truncated",
        "empty",
        "binary",
        "null",
        "list",
        "not-a-list",
        "unknown-field",
        "missing-field",
        "wrong-type",
        "bad-hour",
    ],
)
async def test_a_corrupt_state_file_does_not_stop_startup(
    state_file: Path, restart: Restart, caplog: pytest.LogCaptureFixture, content: bytes
) -> None:
    state_file.parent.mkdir(parents=True)
    state_file.write_bytes(content)
    scheduler = await restart()
    assert scheduler.timers() == []
    assert scheduler.alarms() == []
    assert "starting without timers" in caplog.text
    timer = scheduler.add_timer(60)
    assert json.loads(state_file.read_text(encoding="utf-8"))["timers"][0]["id"] == timer.id
