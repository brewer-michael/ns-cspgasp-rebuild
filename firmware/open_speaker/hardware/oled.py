"""Monochrome 128x64 OLED modules over I2C: SH1106 (1.3"), SSD1306 (0.96"), SSD1309 (2.42").

A small driver written against the controllers' command sets (via smbus2), so it has
no dependencies beyond smbus2 and Pillow and works on every Raspberry Pi model.
"""

from __future__ import annotations

from typing import Any

import numpy as np

_CMD = 0x00
_DATA = 0x40


class Oled:
    def __init__(
        self,
        driver: str = "sh1106",
        bus: int = 1,
        address: int = 0x3C,
        width: int = 128,
        height: int = 64,
        rotate: int = 0,
        contrast: int = 180,
        i2c: Any = None,
    ) -> None:
        if driver not in ("sh1106", "ssd1306", "ssd1309"):
            raise ValueError(f"unsupported OLED driver: {driver}")
        if height % 8:
            raise ValueError("OLED height must be a multiple of 8")
        self.driver = driver
        self.bus_number = bus
        self.address = address
        self.width = width
        self.height = height
        self.rotate = rotate
        self._contrast = contrast
        self._i2c = i2c
        self._msg: Any = None

    # -- low level ------------------------------------------------------------

    def _write(self, control: int, payload: bytes | list[int]) -> None:
        data = bytes(payload)
        if self._msg is None:  # injected test double
            self._i2c.write(self.address, bytes([control]) + data)
            return
        for start in range(0, len(data), 1024):
            chunk = data[start : start + 1024]
            self._i2c.i2c_rdwr(self._msg.write(self.address, bytes([control]) + chunk))

    def command(self, *codes: int) -> None:
        self._write(_CMD, list(codes))

    # -- setup ----------------------------------------------------------------

    def open(self) -> None:
        if self._i2c is None:
            from smbus2 import SMBus, i2c_msg

            self._i2c = SMBus(self.bus_number)
            self._msg = i2c_msg
        flip = self.rotate == 180
        segment_remap = 0xA0 if flip else 0xA1
        com_scan = 0xC0 if flip else 0xC8
        com_pins = 0x12 if self.height == 64 else 0x02
        if self.driver == "sh1106":
            self.command(
                0xAE, 0xD5, 0x80, 0xA8, self.height - 1, 0xD3, 0x00, 0x40,
                0xAD, 0x8B,  # DC-DC converter on
                segment_remap, com_scan, 0xDA, com_pins, 0x81, self._contrast,
                0xD9, 0x22, 0xDB, 0x35, 0xA4, 0xA6,
            )  # fmt: skip
        else:
            charge_pump = [0x8D, 0x14] if self.driver == "ssd1306" else []
            self.command(
                0xAE, 0xD5, 0x80, 0xA8, self.height - 1, 0xD3, 0x00, 0x40,
                *charge_pump,
                0x20, 0x00,  # horizontal addressing
                segment_remap, com_scan, 0xDA, com_pins, 0x81, self._contrast,
                0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6,
            )  # fmt: skip
        self.clear()
        self.command(0xAF)

    def close(self) -> None:
        if self._i2c is not None:
            try:
                self.command(0xAE)
            finally:
                close = getattr(self._i2c, "close", None)
                if close is not None:
                    close()
                self._i2c = None

    # -- drawing --------------------------------------------------------------

    def contrast(self, value: int) -> None:
        self._contrast = max(0, min(255, value))
        self.command(0x81, self._contrast)

    def power(self, on: bool) -> None:
        self.command(0xAF if on else 0xAE)

    def pages(self, image: Any) -> bytes:
        """Pack a 1-bit image into controller pages (8 rows per byte, LSB on top)."""
        if image.size != (self.width, self.height):
            raise ValueError(f"image must be {self.width}x{self.height}")
        pixels = np.asarray(image.convert("1"), dtype=np.uint8) > 0
        pages = pixels.reshape(self.height // 8, 8, self.width)
        return np.packbits(pages, axis=1, bitorder="little").tobytes()

    def show_bytes(self, data: bytes) -> None:
        if self.driver == "sh1106":
            # SH1106 has 132 columns of RAM; the visible 128 start at column 2.
            for page in range(self.height // 8):
                self.command(0xB0 + page, 0x02, 0x10)
                self._write(_DATA, data[page * self.width : (page + 1) * self.width])
        else:
            self.command(0x21, 0, self.width - 1, 0x22, 0, self.height // 8 - 1)
            self._write(_DATA, data)

    def show(self, image: Any) -> None:
        self.show_bytes(self.pages(image))

    def clear(self) -> None:
        self.show_bytes(bytes(self.width * self.height // 8))
