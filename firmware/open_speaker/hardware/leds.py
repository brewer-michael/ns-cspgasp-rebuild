"""WS2812B status LEDs driven from the SPI MOSI pin (GPIO10).

The original firmware used the NeoPixel/rpi_ws281x stack, which needs root. Encoding
the WS2812 waveform as SPI data works as a normal user (spi group) on every Pi model.
Status colours and animations follow the original ``ws2812_status.py``.

On a Pi Zero 2 W / Pi 3 the SPI clock follows the VPU core clock, so the installer
pins it with ``core_freq=250`` in config.txt to keep the LED timing stable.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import logging
import math
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

SPI_HZ = 2_400_000  # 3 SPI bits per WS2812 bit -> 800 kHz
_RESET_BYTES = bytes(96)  # > 280 us low latches the colours


def _encode_table() -> list[bytes]:
    table = []
    for value in range(256):
        bits = 0
        for i in range(7, -1, -1):
            bits = (bits << 3) | (0b110 if value >> i & 1 else 0b100)
        table.append(bits.to_bytes(3, "big"))
    return table


_TABLE = _encode_table()

RGB = tuple[int, int, int]


class Ws2812Spi:
    def __init__(
        self,
        count: int,
        bus: int = 0,
        device: int = 0,
        color_order: str = "GRB",
        spi: Any = None,
    ) -> None:
        self.count = count
        self.bus = bus
        self.device = device
        self.order = [("RGB".index(c)) for c in color_order.upper()]
        self._spi = spi

    def open(self) -> None:
        if self._spi is None:
            import spidev

            spi = spidev.SpiDev()
            spi.open(self.bus, self.device)
            spi.max_speed_hz = SPI_HZ
            spi.mode = 0
            self._spi = spi

    def encode(self, pixels: list[RGB]) -> bytes:
        data = bytearray(b"\x00")
        for pixel in pixels:
            for channel in self.order:
                data += _TABLE[max(0, min(255, int(pixel[channel])))]
        return bytes(data) + _RESET_BYTES

    def show(self, pixels: list[RGB]) -> None:
        if self._spi is None:
            return
        self._spi.writebytes2(self.encode(pixels))

    def close(self) -> None:
        if self._spi is not None:
            with contextlib.suppress(Exception):
                self.show([(0, 0, 0)] * self.count)
            close = getattr(self._spi, "close", None)
            if close is not None:
                close()
            self._spi = None


class Status(enum.Enum):
    OFF = "off"
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"
    MUTED = "muted"
    ALARM = "alarm"


COLORS: dict[str, RGB] = {
    "off": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "cyan": (0, 255, 255),
    "orange": (255, 128, 0),
}

# status -> (colour, pulsing, intensity)
_STYLE: dict[Status, tuple[RGB, bool, float]] = {
    Status.OFF: (COLORS["off"], False, 0.0),
    Status.IDLE: (COLORS["blue"], False, 0.1),
    Status.LISTENING: (COLORS["green"], False, 1.0),
    Status.THINKING: (COLORS["cyan"], True, 1.0),
    Status.SPEAKING: (COLORS["blue"], True, 1.0),
    Status.ERROR: (COLORS["red"], False, 1.0),
    Status.MUTED: (COLORS["red"], False, 0.15),
    Status.ALARM: (COLORS["orange"], True, 1.0),
}

PULSE_PERIOD = 1.6  # seconds for one dim-bright-dim cycle
PULSE_MIN = 0.1


def scale(color: RGB, factor: float) -> RGB:
    return (int(color[0] * factor), int(color[1] * factor), int(color[2] * factor))


class StatusLeds:
    """Shows the assistant's state; runs its own animation task."""

    def __init__(self, strip: Ws2812Spi | Any, brightness: float = 0.3, fps: float = 40) -> None:
        self.strip = strip
        self.brightness = brightness
        self.night = False
        self.fps = fps
        self.status = Status.OFF
        self._flash: tuple[RGB, float] | None = None
        self._changed = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="status-leds")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self.strip.close()

    def set(self, status: Status) -> None:
        if status != self.status:
            self.status = status
            self._changed.set()

    def set_night(self, night: bool) -> None:
        if night != self.night:
            self.night = night
            self._changed.set()

    def flash(self, color: RGB, seconds: float = 0.15) -> None:
        """Briefly show a colour (e.g. white for a volume change), then the status."""
        self._flash = (color, time.monotonic() + seconds)
        self._changed.set()

    def flash_volume(self, level: int) -> None:
        self.flash(scale(COLORS["white"], max(0.2, level / 100)))

    def frame(self, now: float) -> RGB:
        if self._flash is not None:
            color, until = self._flash
            if now < until:
                return scale(color, self._level())
            self._flash = None
        color, pulsing, intensity = _STYLE[self.status]
        if pulsing:
            phase = (math.sin(2 * math.pi * now / PULSE_PERIOD) + 1) / 2
            intensity *= PULSE_MIN + (1 - PULSE_MIN) * phase
        return scale(color, intensity * self._level())

    def _level(self) -> float:
        return self.brightness * (0.3 if self.night else 1.0)

    @property
    def animating(self) -> bool:
        return self._flash is not None or _STYLE[self.status][1]

    async def _run(self) -> None:
        last: RGB | None = None
        while True:
            color = self.frame(time.monotonic())
            if color != last:
                try:
                    self.strip.show([color] * self.strip.count)
                except OSError as err:
                    _LOGGER.error("Status LEDs failed: %s", err)
                last = color
            self._changed.clear()
            if self.animating:
                await asyncio.sleep(1 / self.fps)
            else:
                await self._changed.wait()
