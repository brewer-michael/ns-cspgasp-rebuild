"""Timers and alarms that live on the speaker and survive restarts.

Everything is stored in a small JSON file and checked against the wall clock, so a
reboot or an NTP clock correction at boot does not lose or delay an alarm.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .intents import TOMORROW, describe_clock, describe_repeat

_LOGGER = logging.getLogger(__name__)

# Longest sleep between checks, so clock changes are noticed promptly.
_MAX_SLEEP = 30.0


@dataclass
class Timer:
    id: str
    seconds: float
    ends_at: float
    name: str | None = None
    # "timer", or "snooze" for a snoozed alarm (rings with the alarm sound)
    kind: str = "timer"

    @property
    def label(self) -> str:
        if self.kind == "snooze":
            return "alarm"
        return f"{self.name} timer" if self.name else "timer"


@dataclass
class Alarm:
    id: str
    hour: int
    minute: int
    repeat: list[int] = field(default_factory=list)
    next_at: float = 0.0
    enabled: bool = True

    @property
    def label(self) -> str:
        return "alarm"

    def describe(self, clock_24h: bool = False) -> str:
        text = describe_clock(self.hour, self.minute, clock_24h)
        if self.repeat:
            return f"{text} {describe_repeat(frozenset(self.repeat))}"
        return text


@dataclass
class Ring:
    """Something that is going off right now."""

    kind: str  # "timer" or "alarm"
    label: str
    item_id: str


def next_occurrence(
    hour: int,
    minute: int,
    after: datetime,
    repeat: frozenset[int] | set[int] | list[int] = frozenset(),
    day: int | None = None,
) -> datetime:
    """The first local time strictly after ``after`` matching the alarm rule."""
    base = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    for offset in range(0, 15):
        candidate = base + timedelta(days=offset)
        if candidate <= after:
            continue
        if repeat and candidate.weekday() not in repeat:
            continue
        if day == TOMORROW and candidate.date() != (after + timedelta(days=1)).date():
            continue
        if day is not None and day >= 0 and candidate.weekday() != day:
            continue
        return candidate
    raise ValueError("no matching time")  # pragma: no cover - unreachable


class Scheduler:
    def __init__(
        self,
        state_file: Path,
        on_ring: Callable[[Ring], Awaitable[None]],
        missed_grace_seconds: float = 600.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.state_file = state_file
        self.on_ring = on_ring
        self.missed_grace = missed_grace_seconds
        self.clock = clock
        self._timers: dict[str, Timer] = {}
        self._alarms: dict[str, Alarm] = {}
        self._wakeup = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    # -- lifecycle ------------------------------------------------------------

    async def start(self) -> None:
        try:
            self._load()
        except (AttributeError, TypeError, ValueError) as err:  # valid JSON, wrong shape
            _LOGGER.error("Could not load %s, starting without timers: %s", self.state_file, err)
            self._timers.clear()
            self._alarms.clear()
        self._task = asyncio.create_task(self._run(), name="scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def _now_dt(self) -> datetime:
        return datetime.fromtimestamp(self.clock())

    def _load(self) -> None:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as err:
            _LOGGER.error("Could not read %s, starting without timers: %s", self.state_file, err)
            return
        now = self.clock()
        for item in data.get("timers", []):
            timer = Timer(**item)
            if timer.ends_at < now - self.missed_grace:
                _LOGGER.info("Dropping %s that expired while the speaker was off", timer.label)
                continue
            self._timers[timer.id] = timer
        for item in data.get("alarms", []):
            alarm = Alarm(**item)
            if alarm.enabled and alarm.next_at < now - self.missed_grace:
                if alarm.repeat:
                    alarm.next_at = next_occurrence(
                        alarm.hour, alarm.minute, self._now_dt(), alarm.repeat
                    ).timestamp()
                else:
                    alarm.enabled = False
            if alarm.enabled or alarm.repeat:
                self._alarms[alarm.id] = alarm
        self._save()

    def _save(self) -> None:
        data = {
            "timers": [asdict(t) for t in self._timers.values()],
            "alarms": [asdict(a) for a in self._alarms.values()],
        }
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, self.state_file)
        except OSError as err:
            _LOGGER.error("Could not save timers to %s: %s", self.state_file, err)

    def _changed(self) -> None:
        self._save()
        self._wakeup.set()

    # -- timers ---------------------------------------------------------------

    def add_timer(self, seconds: float, name: str | None = None, kind: str = "timer") -> Timer:
        timer = Timer(uuid.uuid4().hex[:8], seconds, self.clock() + seconds, name, kind)
        self._timers[timer.id] = timer
        self._changed()
        return timer

    def timers(self) -> list[Timer]:
        return sorted(
            (t for t in self._timers.values() if t.kind == "timer"), key=lambda t: t.ends_at
        )

    def remaining(self, timer: Timer) -> float:
        return max(0.0, timer.ends_at - self.clock())

    def find_timers(self, name: str | None) -> list[Timer]:
        timers = self.timers()
        if name is None:
            return timers
        return [t for t in timers if t.name and name in t.name]

    def cancel_timers(self, name: str | None = None, all: bool = False) -> list[Timer]:
        if all:
            cancelled = self.timers()
        else:
            matches = self.find_timers(name)
            # "cancel the timer" with several running: the one ending soonest
            cancelled = matches[:1] if name is None else matches
        for timer in cancelled:
            del self._timers[timer.id]
        if cancelled:
            self._changed()
        return cancelled

    # -- alarms ---------------------------------------------------------------

    def add_alarm(
        self,
        hour: int,
        minute: int,
        repeat: frozenset[int] = frozenset(),
        day: int | None = None,
        ambiguous: bool = False,
    ) -> Alarm:
        now = self._now_dt()
        candidates = [hour]
        if ambiguous and hour < 12:
            candidates.append(hour + 12)
        best = min((next_occurrence(h, minute, now, repeat, day), h) for h in candidates)
        alarm = Alarm(uuid.uuid4().hex[:8], best[1], minute, sorted(repeat), best[0].timestamp())
        self._alarms[alarm.id] = alarm
        self._changed()
        return alarm

    def alarms(self) -> list[Alarm]:
        return sorted((a for a in self._alarms.values() if a.enabled), key=lambda a: a.next_at)

    def next_alarm(self) -> Alarm | None:
        alarms = self.alarms()
        return alarms[0] if alarms else None

    def cancel_alarms(
        self,
        hour: int | None = None,
        minute: int | None = None,
        all: bool = False,
        ambiguous: bool = False,
    ) -> list[Alarm]:
        alarms = self.alarms()
        if all:
            cancelled = alarms
        elif hour is not None:
            hours = {hour, hour + 12} if ambiguous and hour < 12 else {hour}
            cancelled = [a for a in alarms if a.hour in hours and a.minute == (minute or 0)]
        else:
            cancelled = alarms[:1]
        for alarm in cancelled:
            del self._alarms[alarm.id]
        if cancelled:
            self._changed()
        return cancelled

    def snooze(self, minutes: int) -> Timer:
        return self.add_timer(minutes * 60, kind="snooze")

    # -- running --------------------------------------------------------------

    def _due(self) -> list[Ring]:
        now = self.clock()
        rings: list[Ring] = []
        for timer in [t for t in self._timers.values() if t.ends_at <= now]:
            del self._timers[timer.id]
            kind = "alarm" if timer.kind == "snooze" else "timer"
            rings.append(Ring(kind, timer.label, timer.id))
        for alarm in [a for a in self._alarms.values() if a.enabled and a.next_at <= now]:
            if alarm.repeat:
                alarm.next_at = next_occurrence(
                    alarm.hour, alarm.minute, self._now_dt(), alarm.repeat
                ).timestamp()
            else:
                del self._alarms[alarm.id]
            rings.append(Ring("alarm", alarm.label, alarm.id))
        if rings:
            self._save()
        return rings

    def _seconds_until_next(self) -> float:
        times = [t.ends_at for t in self._timers.values()]
        times += [a.next_at for a in self._alarms.values() if a.enabled]
        if not times:
            return _MAX_SLEEP
        return max(0.0, min(min(times) - self.clock(), _MAX_SLEEP))

    async def check(self) -> None:
        """Fire everything that is due (also called by the run loop)."""
        for ring in self._due():
            try:
                await self.on_ring(ring)
            except Exception:
                _LOGGER.exception("Error while ringing %s", ring.label)

    async def _run(self) -> None:
        while True:
            await self.check()
            self._wakeup.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wakeup.wait(), self._seconds_until_next())
