"""Tactile buttons with debouncing, long-press detection and auto-repeat.

Behaviour matches the original firmware's ButtonHandler: PRESS fires immediately,
LONG_PRESS after 0.8 s, and the volume buttons then REPEAT every 0.1 s after a
0.3 s delay. SHORT_PRESS is added for buttons that do one thing on a tap and
another on a long press.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import logging
from collections.abc import Callable
from typing import Any

_LOGGER = logging.getLogger(__name__)


class ButtonEvent(enum.Enum):
    PRESS = "press"
    RELEASE = "release"
    SHORT_PRESS = "short_press"  # released before the long-press time
    LONG_PRESS = "long_press"
    REPEAT = "repeat"


class Buttons:
    """Watches GPIO buttons (wired to GND, internal pull-ups) and reports events.

    gpiozero calls back from its own thread; events are delivered on the asyncio loop.
    """

    def __init__(
        self,
        pins: dict[str, int],
        on_event: Callable[[str, ButtonEvent], Any],
        long_press: float = 0.8,
        repeat_delay: float = 0.3,
        repeat_interval: float = 0.1,
        bounce: float = 0.05,
        repeatable: frozenset[str] = frozenset({"volume_up", "volume_down"}),
        pin_factory: Any = None,
    ) -> None:
        self.pins = pins
        self.on_event = on_event
        self.long_press = long_press
        self.repeat_delay = repeat_delay
        self.repeat_interval = repeat_interval
        self.bounce = bounce
        self.repeatable = repeatable
        self.pin_factory = pin_factory
        self._buttons: dict[str, Any] = {}
        self._holds: dict[str, asyncio.Task[None]] = {}
        self._long_fired: set[str] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        from gpiozero import Button

        self._loop = asyncio.get_running_loop()
        for name, pin in self.pins.items():
            button = Button(
                pin,
                pull_up=True,
                bounce_time=self.bounce or None,
                pin_factory=self.pin_factory,
            )
            button.when_pressed = lambda _b=None, n=name: self._threadsafe(self._pressed, n)
            button.when_released = lambda _b=None, n=name: self._threadsafe(self._released, n)
            self._buttons[name] = button
        _LOGGER.info("Buttons ready: %s", ", ".join(f"{n}=GPIO{p}" for n, p in self.pins.items()))

    def close(self) -> None:
        for task in self._holds.values():
            task.cancel()
        self._holds.clear()
        for button in self._buttons.values():
            with contextlib.suppress(Exception):
                button.close()
        self._buttons.clear()

    def is_pressed(self, name: str) -> bool:
        button = self._buttons.get(name)
        return bool(button and button.is_pressed)

    def _threadsafe(self, func: Callable[[str], None], name: str) -> None:
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(func, name)

    def _emit(self, name: str, event: ButtonEvent) -> None:
        try:
            self.on_event(name, event)
        except Exception:
            _LOGGER.exception("Button handler failed for %s %s", name, event.value)

    def _pressed(self, name: str) -> None:
        if name in self._holds:  # bounce / duplicate edge
            return
        self._long_fired.discard(name)
        self._emit(name, ButtonEvent.PRESS)
        self._holds[name] = asyncio.create_task(self._hold(name))

    def _released(self, name: str) -> None:
        task = self._holds.pop(name, None)
        if task is None:
            return
        task.cancel()
        long_fired = name in self._long_fired
        if not long_fired:
            self._emit(name, ButtonEvent.SHORT_PRESS)
        if not (long_fired and name in self.repeatable):
            self._emit(name, ButtonEvent.RELEASE)

    async def _hold(self, name: str) -> None:
        await asyncio.sleep(self.long_press)
        self._long_fired.add(name)
        self._emit(name, ButtonEvent.LONG_PRESS)
        if name not in self.repeatable:
            return
        await asyncio.sleep(self.repeat_delay)
        while True:
            self._emit(name, ButtonEvent.REPEAT)
            await asyncio.sleep(self.repeat_interval)
