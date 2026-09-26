"""TM1637 4-digit 7-segment display (bit-banged two-wire protocol).

Ported from the original firmware's ``tm1637_driver.py`` onto gpiozero pins. The
DIO line is switched to input for the ACK bit, so the Pi never drives it high while
the TM1637 pulls it low.
"""

from __future__ import annotations

import time
from typing import Any

# Segment encoding: 0bDPGFEDCBA
#      A
#     ---
#  F |   | B
#     -G-
#  E |   | C
#     ---
#      D   .DP
DIGITS = {
    0: 0b00111111, 1: 0b00000110, 2: 0b01011011, 3: 0b01001111, 4: 0b01100110,
    5: 0b01101101, 6: 0b01111101, 7: 0b00000111, 8: 0b01111111, 9: 0b01101111,
}  # fmt: skip

CHARS = {
    " ": 0b00000000, "-": 0b01000000, "_": 0b00001000, "°": 0b01100011,
    "A": 0b01110111, "b": 0b01111100, "C": 0b00111001, "c": 0b01011000,
    "d": 0b01011110, "E": 0b01111001, "F": 0b01110001, "H": 0b01110110,
    "h": 0b01110100, "I": 0b00000110, "J": 0b00011110, "L": 0b00111000,
    "n": 0b01010100, "o": 0b01011100, "P": 0b01110011, "r": 0b01010000,
    "S": 0b01101101, "t": 0b01111000, "U": 0b00111110, "u": 0b00011100,
    "V": 0b00111110, "Y": 0b01101110,
}  # fmt: skip

CMD_DATA = 0x40
CMD_ADDR = 0xC0
CMD_DISPLAY = 0x80


def encode(char: str | int) -> int:
    if isinstance(char, int) and 0 <= char <= 9:
        return DIGITS[char]
    if isinstance(char, str) and len(char) == 1:
        if char.isdigit():
            return DIGITS[int(char)]
        return CHARS.get(char, CHARS.get(char.upper(), CHARS.get(char.lower(), 0)))
    return 0


class TM1637:
    def __init__(self, clk_pin: int = 23, dio_pin: int = 24, pin_factory: Any = None) -> None:
        if pin_factory is None:
            from gpiozero import Device

            pin_factory = Device.ensure_pin_factory()
        self._clk = pin_factory.pin(clk_pin)
        self._dio = pin_factory.pin(dio_pin)
        self._clk.function = "output"
        self._dio.function = "output"
        self._clk.state = 1
        self._dio.state = 1
        self._brightness = 7
        self._on = True
        self.last_segments: list[int] = [0, 0, 0, 0]

    @staticmethod
    def _delay() -> None:
        time.sleep(0.00001)

    def _start(self) -> None:
        self._dio.state = 1
        self._clk.state = 1
        self._delay()
        self._dio.state = 0
        self._delay()

    def _stop(self) -> None:
        self._clk.state = 0
        self._delay()
        self._dio.state = 0
        self._delay()
        self._clk.state = 1
        self._delay()
        self._dio.state = 1
        self._delay()

    def _write_byte(self, data: int) -> None:
        for _ in range(8):  # LSB first
            self._clk.state = 0
            self._delay()
            self._dio.state = data & 0x01
            self._delay()
            self._clk.state = 1
            self._delay()
            data >>= 1
        # ACK: release DIO while the TM1637 pulls it low for one clock.
        self._clk.state = 0
        self._dio.function = "input"
        self._delay()
        self._clk.state = 1
        self._delay()
        self._clk.state = 0
        self._dio.function = "output"
        self._delay()

    def _write_control(self) -> None:
        self._start()
        self._write_byte(CMD_DISPLAY | (0x08 | self._brightness if self._on else 0))
        self._stop()

    def brightness(self, level: int) -> None:
        self._brightness = max(0, min(7, level))
        self._write_control()

    def power(self, on: bool) -> None:
        self._on = on
        self._write_control()

    def show_segments(self, segments: list[int]) -> None:
        segments = [*segments, 0, 0, 0, 0][:4]
        self._start()
        self._write_byte(CMD_DATA)
        self._stop()
        self._start()
        self._write_byte(CMD_ADDR)
        for segment in segments:
            self._write_byte(segment)
        self._stop()
        self._write_control()
        self.last_segments = segments

    def show(self, text: str, colon: bool = False) -> None:
        """Show up to 4 characters; the colon is the DP bit of the second digit."""
        segments = [encode(c) for c in str(text)[:4].ljust(4)]
        if colon:
            segments[1] |= 0x80
        self.show_segments(segments)

    def show_time(self, hour: int, minute: int, colon: bool = True) -> None:
        self.show(f"{hour:2d}{minute:02d}", colon)

    def show_temperature(self, temperature: float, unit: str = "C") -> None:
        if -9 <= temperature <= 99:
            self.show(f"{round(temperature):2d}°{unit}")
        else:
            self.show(f"{round(temperature):3d}{unit}")

    def show_volume(self, level: int) -> None:
        self.show(f"V{level:3d}"[:4])

    def clear(self) -> None:
        self.show("    ")

    def close(self) -> None:
        self.clear()
        self.power(False)
        self._clk.close()
        self._dio.close()
