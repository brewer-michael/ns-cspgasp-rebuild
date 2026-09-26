"""The front display: always the time and the temperature, like the original.

The original Insignia display showed the time and temperature at all times and
swapped other values into the temperature slot for a moment (the volume for a few
seconds while adjusting it, "bt" in Bluetooth mode) and used the whole display only
for modes such as pairing ("net"). This keeps the display compact and clean; the
assistant's listening/thinking/speaking state is shown by the status LEDs instead.

Two renderers are provided: a 128x64 OLED (default) and a TM1637 4-digit display.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from datetime import time as dtime
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
)


@dataclass
class DisplayState:
    now: datetime
    clock_24h: bool = False
    alarm_set: bool = False
    # The temperature slot: the temperature, or whatever is swapped in right now.
    secondary: str | None = None
    # True while a value is swapped in for a moment (volume, mic on/off, ...).
    swap: bool = False
    # "alarm" blinks the time; "timer" blinks the secondary slot.
    ringing: str | None = None
    # A mode that takes over the whole display (e.g. "net" while pairing).
    mode: str | None = None


def parse_clock(value: str | None) -> dtime | None:
    if not value:
        return None
    hour, minute = value.split(":")
    return dtime(int(hour), int(minute))


def is_night(now: datetime, start: dtime | None, end: dtime | None) -> bool:
    if start is None or end is None or start == end:
        return False
    current = now.time()
    if start < end:
        return start <= current < end
    return current >= start or current < end


def format_countdown(seconds: float) -> str:
    seconds = max(0, int(seconds + 0.999))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def clock_digits(now: datetime, clock_24h: bool) -> tuple[str, str | None]:
    """("7:42", "PM") or ("19:42", None)."""
    if clock_24h:
        return f"{now.hour:02d}:{now.minute:02d}", None
    return f"{now.hour % 12 or 12}:{now.minute:02d}", "AM" if now.hour < 12 else "PM"


def blink_on(now: datetime) -> bool:
    return now.second % 2 == 0


class Renderer(ABC):
    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def render(self, state: DisplayState, night: bool) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# OLED


class OledRenderer(Renderer):
    SHIFTS = [(0, 0), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]

    def __init__(
        self,
        device: Any,
        contrast: int = 180,
        night_contrast: int = 8,
        pixel_shift: bool = True,
        font: str | None = None,
    ) -> None:
        self.device = device
        self.contrast = contrast
        self.night_contrast = night_contrast
        self.pixel_shift = pixel_shift
        self.font_path = font
        self._fonts: dict[int, Any] = {}
        self._last: bytes | None = None
        self._last_contrast: int | None = None

    def open(self) -> None:
        self.device.open()

    def close(self) -> None:
        self.device.close()

    def font(self, size: int) -> Any:
        if size not in self._fonts:
            from PIL import ImageFont

            paths = [self.font_path] if self.font_path else []
            for path in [*paths, *FONT_CANDIDATES]:
                if path and Path(path).is_file():
                    self._fonts[size] = ImageFont.truetype(path, size)
                    break
            else:
                try:
                    self._fonts[size] = ImageFont.load_default(size)
                except TypeError:  # Pillow < 10.1 only has a tiny bitmap font
                    self._fonts[size] = ImageFont.load_default()
        return self._fonts[size]

    def draw(self, state: DisplayState) -> Any:
        from PIL import Image, ImageDraw

        width, height = self.device.width, self.device.height
        image = Image.new("1", (width, height))
        draw = ImageDraw.Draw(image)
        dx = dy = 0
        if self.pixel_shift:  # nudge everything a pixel every few minutes (burn-in)
            minute = state.now.hour * 60 + state.now.minute
            dx, dy = self.SHIFTS[(minute // 3) % len(self.SHIFTS)]

        if state.mode:
            font = self.font(40)
            left, top, right, bottom = draw.textbbox((0, 0), state.mode, font=font)
            x = (width - (right - left)) // 2 - left + dx
            y = (height - (bottom - top)) // 2 - top + dy
            draw.text((x, y), state.mode, font=font, fill=1)
            return image

        blink = blink_on(state.now)
        small = self.font(11)
        digits, meridiem = clock_digits(state.now, state.clock_24h)
        big = self.font(36 if len(digits) <= 4 else 32)
        left, top, right, _ = draw.textbbox((0, 0), digits, font=big)
        digits_right = width - 2 + dx
        x = digits_right - (right - left) - left
        if state.ringing != "alarm" or blink:
            draw.text((x, 3 - top + dy), digits, font=big, fill=1)
            # Left margin markers, like the original display's "AL" / "PM".
            if state.alarm_set:
                draw.text((1 + dx, 4 + dy), "AL", font=small, fill=1)
            if meridiem:
                draw.text((1 + dx, 20 + dy), meridiem, font=small, fill=1)

        if state.secondary and (state.ringing != "timer" or blink):
            medium = self.font(18)
            left, top, right, _ = draw.textbbox((0, 0), state.secondary, font=medium)
            sx = digits_right - (right - left) - left
            draw.text((sx, 43 - top + dy), state.secondary, font=medium, fill=1)
        return image

    def render(self, state: DisplayState, night: bool) -> None:
        contrast = self.night_contrast if night else self.contrast
        if contrast != self._last_contrast:
            self.device.contrast(contrast)
            self._last_contrast = contrast
        data = self.device.pages(self.draw(state))
        if data != self._last:
            self.device.show_bytes(data)
            self._last = data


# ---------------------------------------------------------------------------
# TM1637


class Tm1637Renderer(Renderer):
    """Four digits: the time, with the temperature slot's value swapped in now and then."""

    def __init__(self, device: Any, brightness: int = 3, night_brightness: int = 0) -> None:
        self.device = device
        self.brightness = brightness
        self.night_brightness = night_brightness
        self._last: tuple[str, bool] | None = None
        self._last_brightness: int | None = None

    def open(self) -> None:
        self.device.brightness(self.brightness)

    def close(self) -> None:
        self.device.close()

    @staticmethod
    def _four(text: str) -> str:
        text = text.replace("°F", "°").replace("°C", "°").replace("\u2212", "-")
        text = text.replace("Vol ", "V").replace(":", "")
        return text[-4:].rjust(4)

    def text(self, state: DisplayState, swapped: bool) -> tuple[str, bool]:
        now = state.now
        blink = blink_on(now)
        if state.mode:
            return state.mode[:4].ljust(4), False
        if state.ringing == "timer":
            return (" End" if blink else "    "), False
        if state.ringing == "alarm" and not blink:
            return "    ", False
        if swapped and state.secondary:
            return self._four(state.secondary), ":" in state.secondary
        if state.clock_24h:
            digits = f"{now.hour:02d}{now.minute:02d}"
        else:
            digits = f"{now.hour % 12 or 12:2d}{now.minute:02d}"
        return digits, blink

    def render(self, state: DisplayState, night: bool) -> None:
        brightness = self.night_brightness if night else self.brightness
        if brightness != self._last_brightness:
            self.device.brightness(brightness)
            self._last_brightness = brightness
        # With four digits the temperature slot takes turns with the time; swapped-in
        # values (volume...) show straight away.
        swapped = state.swap or state.now.second % 10 >= 7
        text = self.text(state, swapped)
        if text != self._last:
            self.device.show(text[0], colon=text[1])
            self._last = text


# ---------------------------------------------------------------------------
# Controller


class Display:
    """Redraws once per second, or immediately after :meth:`refresh`."""

    def __init__(
        self,
        renderer: Renderer,
        state: Callable[[], DisplayState],
        night_start: str | None = None,
        night_end: str | None = None,
        on_night: Callable[[bool], None] | None = None,
    ) -> None:
        self.renderer = renderer
        self.state = state
        self.night_start = parse_clock(night_start)
        self.night_end = parse_clock(night_end)
        self.on_night = on_night
        self.night = False
        self._refresh = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="display")

    async def _call(self, func: Callable[..., Any], *args: Any) -> Any:
        return await asyncio.get_running_loop().run_in_executor(self._executor, func, *args)

    async def start(self) -> None:
        await self._call(self.renderer.open)
        self._task = asyncio.create_task(self._run(), name="display")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        with contextlib.suppress(Exception):
            await self._call(self.renderer.close)
        self._executor.shutdown(wait=False)

    def refresh(self) -> None:
        self._refresh.set()

    async def _run(self) -> None:
        while True:
            self._refresh.clear()
            state = self.state()
            night = is_night(state.now, self.night_start, self.night_end)
            if night != self.night:
                self.night = night
                if self.on_night is not None:
                    self.on_night(night)
            try:
                await self._call(self.renderer.render, state, night)
            except OSError as err:
                _LOGGER.error("Display update failed: %s", err)
                await asyncio.sleep(5)
            # wake at the next second boundary (or earlier on refresh)
            delay = 1.0 - (datetime.now().microsecond / 1_000_000)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._refresh.wait(), max(0.05, delay))
