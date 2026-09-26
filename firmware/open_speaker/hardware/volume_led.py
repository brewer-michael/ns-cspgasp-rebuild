"""Single LED whose brightness shows the volume (PWM on GPIO12 in the reference build)."""

from __future__ import annotations

import contextlib
from typing import Any


class VolumeLed:
    def __init__(self, pin: int, max_brightness: float = 0.6, pin_factory: Any = None) -> None:
        from gpiozero import PWMLED

        self.max_brightness = max_brightness
        self.night = False
        self._led = PWMLED(pin, pin_factory=pin_factory)

    def show(self, level: int, muted: bool = False) -> None:
        value = 0.0 if muted else (level / 100) * self.max_brightness
        if self.night:
            value *= 0.3
        self._led.value = max(0.0, min(1.0, value))

    @property
    def value(self) -> float:
        return float(self._led.value)

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._led.off()
            self._led.close()
