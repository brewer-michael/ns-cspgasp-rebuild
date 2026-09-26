"""Hardware drivers on mock pins and fake buses: buttons, TM1637, OLED, status and volume LEDs."""

from __future__ import annotations

import asyncio
import itertools
import sys
import threading
import types
from typing import Any

import numpy as np
import pytest
from conftest import wait_for
from gpiozero.pins.mock import MockFactory, MockPin, MockPWMPin
from PIL import Image

from open_speaker.hardware.buttons import ButtonEvent, Buttons
from open_speaker.hardware.leds import SPI_HZ, Status, StatusLeds, Ws2812Spi, scale
from open_speaker.hardware.oled import Oled
from open_speaker.hardware.tm1637 import TM1637, encode
from open_speaker.hardware.volume_led import VolumeLed

PRESS = ButtonEvent.PRESS
RELEASE = ButtonEvent.RELEASE
SHORT = ButtonEvent.SHORT_PRESS
LONG = ButtonEvent.LONG_PRESS
REPEAT = ButtonEvent.REPEAT
TOLERANCE = 0.005

RGB = tuple[int, int, int]

# ---------------------------------------------------------------------------
# Buttons


class ButtonRig:
    """Buttons on mock pins; records each event with the time and thread it arrived on."""

    def __init__(self, pins: dict[str, int], **kwargs: Any) -> None:
        self.factory = MockFactory()
        self.pins = pins
        self.events: list[tuple[str, ButtonEvent]] = []
        self.times: list[float] = []
        self.threads: set[int] = set()
        options = {"long_press": 0.08, "repeat_delay": 0.05, "repeat_interval": 0.02, "bounce": 0}
        options.update(kwargs)
        self.buttons = Buttons(pins, self.on_event, pin_factory=self.factory, **options)

    def on_event(self, name: str, event: ButtonEvent) -> None:
        self.events.append((name, event))
        self.times.append(asyncio.get_running_loop().time())
        self.threads.add(threading.get_ident())

    def pin(self, name: str) -> MockPin:
        return self.factory.pin(self.pins[name])

    async def press(self, name: str) -> None:
        # gpiozero reports edges from its own thread
        await asyncio.to_thread(self.pin(name).drive_low)

    async def release(self, name: str) -> None:
        await asyncio.to_thread(self.pin(name).drive_high)

    def of(self, name: str) -> list[ButtonEvent]:
        return [event for n, event in self.events if n == name]


@pytest.fixture
async def rig():
    rigs: list[ButtonRig] = []

    def make(pins: dict[str, int] | None = None, **kwargs: Any) -> ButtonRig:
        new = ButtonRig(pins or {"action": 5}, **kwargs)
        new.buttons.start()
        rigs.append(new)
        return new

    yield make
    for each in rigs:
        each.buttons.close()
        each.factory.close()


async def test_tap_reports_press_short_press_and_release_on_the_loop_thread(rig) -> None:
    r = rig()
    await r.press("action")
    await wait_for(lambda: r.events == [("action", PRESS)])
    assert r.buttons.is_pressed("action")
    await r.release("action")
    await wait_for(lambda: len(r.events) == 3)
    assert r.events == [("action", PRESS), ("action", SHORT), ("action", RELEASE)]
    assert not r.buttons.is_pressed("action")
    assert r.threads == {threading.get_ident()}
    await asyncio.sleep(r.buttons.long_press + 0.05)
    assert len(r.events) == 3


async def test_long_press_on_a_plain_button_does_not_repeat(rig) -> None:
    r = rig(long_press=0.05)
    await r.press("action")
    await wait_for(lambda: ("action", LONG) in r.events)
    await asyncio.sleep(0.1)
    assert r.events == [("action", PRESS), ("action", LONG)]
    assert r.times[1] - r.times[0] >= 0.05 - TOLERANCE
    await r.release("action")
    await wait_for(lambda: len(r.events) == 3)
    assert r.events[2] == ("action", RELEASE)


async def test_volume_buttons_repeat_while_held(rig) -> None:
    r = rig({"volume_up": 17}, long_press=0.06, repeat_delay=0.05, repeat_interval=0.02)
    await r.press("volume_up")
    await wait_for(lambda: r.of("volume_up").count(REPEAT) >= 4)
    await r.release("volume_up")
    await asyncio.sleep(0)
    count = len(r.events)
    await asyncio.sleep(0.08)
    assert len(r.events) == count
    kinds = r.of("volume_up")
    assert kinds[:2] == [PRESS, LONG]
    # Like the original firmware, a button that was repeating reports no release.
    assert set(kinds[2:]) == {REPEAT}
    times = r.times
    assert times[1] - times[0] >= 0.06 - TOLERANCE
    assert times[2] - times[1] >= 0.05 - TOLERANCE
    assert all(b - a >= 0.02 - TOLERANCE for a, b in itertools.pairwise(times[2:]))


async def test_tapping_a_volume_button_is_a_short_press(rig) -> None:
    r = rig({"volume_down": 27})
    await r.press("volume_down")
    await wait_for(lambda: r.events == [("volume_down", PRESS)])
    await r.release("volume_down")
    await wait_for(lambda: len(r.events) == 3)
    assert r.of("volume_down") == [PRESS, SHORT, RELEASE]


async def test_buttons_are_tracked_independently(rig) -> None:
    pins = {"action": 5, "volume_down": 27}
    r = rig(pins, long_press=0.08, repeat_delay=0.02, repeat_interval=0.02)
    await r.press("volume_down")
    await r.press("action")
    await r.release("action")
    await wait_for(lambda: REPEAT in r.of("volume_down"))
    assert r.of("action") == [PRESS, SHORT, RELEASE]
    assert r.buttons.is_pressed("volume_down")
    assert not r.buttons.is_pressed("action")
    assert not r.buttons.is_pressed("unknown")
    await r.release("volume_down")


async def test_a_failing_handler_does_not_stop_later_events(rig, caplog) -> None:
    r = rig(long_press=0.03)

    def on_event(name: str, event: ButtonEvent) -> None:
        r.events.append((name, event))
        if event is PRESS:
            raise RuntimeError("handler bug")

    r.buttons.on_event = on_event
    await r.press("action")
    await wait_for(lambda: ("action", LONG) in r.events)
    await r.release("action")
    await wait_for(lambda: len(r.events) == 3)
    assert r.events == [("action", PRESS), ("action", LONG), ("action", RELEASE)]
    assert "Button handler failed for action press" in caplog.text


async def test_pins_use_pull_ups_and_the_bounce_time(rig) -> None:
    pin = rig({"mute": 22}, bounce=0.05).pin("mute")
    assert (pin.function, pin.pull, pin.bounce) == ("input", "up", pytest.approx(0.05))
    assert rig({"mute": 22}, bounce=0).pin("mute").bounce is None


async def test_close_cancels_a_pending_long_press_and_releases_the_pins(rig) -> None:
    r = rig(long_press=0.05)
    await r.press("action")
    await wait_for(lambda: r.events == [("action", PRESS)])
    # gpiozero's hold thread only notices close() once a held button is let go
    threading.Timer(0.02, r.pin("action").drive_high).start()
    r.buttons.close()
    await asyncio.sleep(0.1)
    await r.press("action")
    await asyncio.sleep(0.02)
    assert r.events == [("action", PRESS)]
    assert r.pin("action").when_changed is None
    assert not r.buttons.is_pressed("action")


def test_edges_after_the_loop_has_closed_are_dropped() -> None:
    factory = MockFactory()
    events: list[tuple[str, ButtonEvent]] = []
    buttons = Buttons({"action": 5}, lambda *e: events.append(e), bounce=0, pin_factory=factory)
    loop = asyncio.new_event_loop()

    async def start() -> None:
        buttons.start()

    loop.run_until_complete(start())
    loop.close()
    factory.pin(5).drive_low()
    factory.pin(5).drive_high()
    buttons.close()
    factory.close()
    assert events == []


# ---------------------------------------------------------------------------
# TM1637


class RecordingPin(MockPin):
    """Logs every level and direction change to the factory's shared log."""

    def _change_state(self, value: Any) -> bool:
        changed = super()._change_state(value)
        if changed:
            self.factory.log.append((self.info.name, "state", bool(value)))
        return changed

    def _set_function(self, value: str) -> None:
        super()._set_function(value)
        self.factory.log.append((self.info.name, "function", value))


class RecordingFactory(MockFactory):
    def __init__(self) -> None:
        super().__init__(pin_class=RecordingPin)
        self.log: list[tuple[str, str, Any]] = []


def decode_tm1637(log: list[tuple[str, str, Any]], clk: str, dio: str) -> list[list[int]]:
    """Decode START/STOP frames of bytes sent LSB first, each followed by one ACK clock.

    DIO is sampled on the rising CLK edge and the bit is committed on the falling edge,
    unless DIO changes while CLK is high (a START or STOP condition). During the ACK
    clock the Pi must have released DIO (switched it to input).
    """
    level = {clk: True, dio: True}  # idle bus
    released = False
    frames: list[list[int]] = []
    frame: list[int] | None = None
    byte = bits = 0
    pending: str | int | None = None
    for name, kind, value in log:
        if kind == "function":
            if name == dio:
                released = value == "input"
            continue
        before, level[name] = level[name], value
        if name == dio:
            if level[clk]:
                assert not released, "DIO moved while released"
                pending = None
                if before and not value:
                    assert frame is None, "START inside a frame"
                    frame, byte, bits = [], 0, 0
                elif not before and value:
                    assert frame is not None and bits == 0, "STOP outside a frame or mid-byte"
                    frames.append(frame)
                    frame = None
        elif frame is not None:
            if value:
                pending = "ack" if released else int(level[dio])
            elif pending is not None:
                if pending == "ack":
                    assert bits == 8, f"ACK clock after {bits} data bits"
                    frame.append(byte)
                    byte = bits = 0
                else:
                    assert bits < 8, "a ninth data bit instead of an ACK clock"
                    byte |= int(pending) << bits
                    bits += 1
                pending = None
    assert frame is None, "unterminated frame"
    assert level == {clk: True, dio: True}, "bus not left idle"
    return frames


class Tm1637Rig:
    def __init__(self) -> None:
        self.factory = RecordingFactory()
        self.display = TM1637(clk_pin=23, dio_pin=24, pin_factory=self.factory)
        self.factory.log.clear()

    def sent(self) -> list[list[int]]:
        frames = decode_tm1637(self.factory.log, "GPIO23", "GPIO24")
        self.factory.log.clear()
        return frames

    def segments(self) -> list[int]:
        frames = self.sent()
        assert len(frames) == 3
        assert frames[0] == [0x40]  # data command: write with auto-increment
        assert frames[1][0] == 0xC0  # starting at digit 0
        assert len(frames[2]) == 1 and frames[2][0] & 0xF0 == 0x80  # display control
        assert frames[1][1:] == self.display.last_segments
        return frames[1][1:]


@pytest.fixture
def tm() -> Tm1637Rig:
    return Tm1637Rig()


def test_encode() -> None:
    assert encode(8) == 0x7F
    assert [encode(d) for d in (0, 1, 7)] == [0x3F, 0x06, 0x07]
    assert encode("4") == encode(4) == 0x66
    assert encode("A") == encode("a") == 0x77
    assert encode("b") == encode("B") == 0x7C
    assert (encode("C"), encode("c")) == (0x39, 0x58)
    assert (encode("°"), encode("-"), encode("_"), encode(" ")) == (0x63, 0x40, 0x08, 0x00)
    for unknown in ("?", "10", "", 10, -1):
        assert encode(unknown) == 0


def test_tm1637_show_sends_data_address_and_control_commands(tm: Tm1637Rig) -> None:
    tm.display.show("1234")
    assert tm.sent() == [[0x40], [0xC0, 0x06, 0x5B, 0x4F, 0x66], [0x8F]]
    assert tm.display.last_segments == [0x06, 0x5B, 0x4F, 0x66]


def test_tm1637_show_pads_and_truncates(tm: Tm1637Rig) -> None:
    tm.display.show("Hi")
    assert tm.segments() == [0x76, 0x06, 0x00, 0x00]
    tm.display.show("Hello")
    assert tm.segments() == [0x76, 0x79, 0x38, 0x38]
    tm.display.show_segments([0x01, 0x02])
    assert tm.segments() == [0x01, 0x02, 0x00, 0x00]


def test_tm1637_show_time_uses_the_second_digit_dp_as_colon(tm: Tm1637Rig) -> None:
    tm.display.show_time(7, 5)
    assert tm.segments() == [0x00, 0x07 | 0x80, 0x3F, 0x6D]
    tm.display.show_time(12, 34, colon=False)
    assert tm.segments() == [0x06, 0x5B, 0x4F, 0x66]
    tm.display.show("1234", colon=True)
    assert tm.segments() == [0x06, 0x5B | 0x80, 0x4F, 0x66]


@pytest.mark.parametrize(
    ("temperature", "unit", "expected"),
    [
        (21.6, "C", [0x5B, 0x5B, 0x63, 0x39]),  # "22°C"
        (7, "C", [0x00, 0x07, 0x63, 0x39]),  # " 7°C"
        (-5, "C", [0x40, 0x6D, 0x63, 0x39]),  # "-5°C"
        (72, "F", [0x07, 0x5B, 0x63, 0x71]),  # "72°F"
        (104.4, "F", [0x06, 0x3F, 0x66, 0x71]),  # "104F"
        (-12, "C", [0x40, 0x06, 0x5B, 0x39]),  # "-12C"
    ],
)
def test_tm1637_show_temperature(
    tm: Tm1637Rig, temperature: float, unit: str, expected: list[int]
) -> None:
    tm.display.show_temperature(temperature, unit)
    assert tm.segments() == expected


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (45, [0x3E, 0x00, 0x66, 0x6D]),  # "V 45"
        (100, [0x3E, 0x06, 0x3F, 0x3F]),  # "V100"
        (5, [0x3E, 0x00, 0x00, 0x6D]),  # "V  5"
    ],
)
def test_tm1637_show_volume(tm: Tm1637Rig, level: int, expected: list[int]) -> None:
    tm.display.show_volume(level)
    assert tm.segments() == expected


def test_tm1637_brightness_and_power(tm: Tm1637Rig) -> None:
    tm.display.brightness(3)
    assert tm.sent() == [[0x8B]]
    tm.display.brightness(12)
    assert tm.sent() == [[0x8F]]
    tm.display.brightness(-4)
    assert tm.sent() == [[0x88]]
    tm.display.brightness(2)
    assert tm.sent() == [[0x8A]]
    tm.display.power(False)
    assert tm.sent() == [[0x80]]
    tm.display.show("8888")
    assert tm.sent()[2] == [0x80]  # new digits do not switch the display back on
    tm.display.power(True)
    assert tm.sent() == [[0x8A]]


def test_tm1637_clear_and_close(tm: Tm1637Rig) -> None:
    tm.display.show("8888")
    tm.sent()
    tm.display.clear()
    assert tm.segments() == [0, 0, 0, 0]
    tm.display.close()
    assert tm.sent() == [[0x40], [0xC0, 0, 0, 0, 0], [0x8F], [0x80]]
    assert tm.factory.pin(23).function == "input"
    assert tm.factory.pin(24).function == "input"


# ---------------------------------------------------------------------------
# OLED


class FakeI2C:
    """The bus object :class:`Oled` accepts: ``write(address, data)`` and ``close()``."""

    def __init__(self) -> None:
        self.writes: list[tuple[int, bytes]] = []
        self.closed = False

    def write(self, address: int, data: bytes) -> None:
        self.writes.append((address, bytes(data)))

    def close(self) -> None:
        self.closed = True

    def take(self) -> list[bytes]:
        writes, self.writes = self.writes, []
        return [data for _, data in writes]


def cmd(*codes: int) -> bytes:
    return bytes([0x00, *codes])


def dat(payload: bytes) -> bytes:
    return b"\x40" + payload


def init_sequence(driver: str, contrast: int = 180, flip: bool = False, height: int = 64) -> bytes:
    remap, scan = (0xA0, 0xC0) if flip else (0xA1, 0xC8)
    com_pins = 0x12 if height == 64 else 0x02
    head = [0xAE, 0xD5, 0x80, 0xA8, height - 1, 0xD3, 0x00, 0x40]
    tail = [remap, scan, 0xDA, com_pins, 0x81, contrast]
    if driver == "sh1106":
        return cmd(*head, 0xAD, 0x8B, *tail, 0xD9, 0x22, 0xDB, 0x35, 0xA4, 0xA6)
    pump = [0x8D, 0x14] if driver == "ssd1306" else []
    return cmd(*head, *pump, 0x20, 0x00, *tail, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6)


def reference_pages(image: Image.Image) -> bytes:
    """8 rows per byte with the top row in bit 0; pages top to bottom, columns left to right."""
    width, height = image.size
    out = bytearray()
    for page in range(height // 8):
        for x in range(width):
            out.append(sum(1 << bit for bit in range(8) if image.getpixel((x, page * 8 + bit))))
    return bytes(out)


def frame_writes(driver: str, data: bytes, width: int = 128, height: int = 64) -> list[bytes]:
    if driver == "sh1106":
        writes = []
        for page in range(height // 8):
            writes += [cmd(0xB0 + page, 0x02, 0x10), dat(data[page * width : (page + 1) * width])]
        return writes
    return [cmd(0x21, 0, width - 1, 0x22, 0, height // 8 - 1), dat(data)]


@pytest.mark.parametrize("driver", ["sh1106", "ssd1306", "ssd1309"])
@pytest.mark.parametrize("rotate", [0, 180])
def test_oled_open_initialises_clears_and_switches_on(driver: str, rotate: int) -> None:
    bus = FakeI2C()
    oled = Oled(driver, address=0x3D, rotate=rotate, contrast=200, i2c=bus)
    oled.open()
    assert {address for address, _ in bus.writes} == {0x3D}
    writes = bus.take()
    assert writes[0] == init_sequence(driver, 200, flip=rotate == 180)
    assert writes[1:-1] == frame_writes(driver, bytes(1024))
    assert writes[-1] == cmd(0xAF)


def test_oled_sh1106_default_init_sequence() -> None:
    bus = FakeI2C()
    Oled(i2c=bus).open()
    assert bus.writes[0] == (
        0x3C,
        bytes.fromhex("00 ae d5 80 a8 3f d3 00 40 ad 8b a1 c8 da 12 81 b4 d9 22 db 35 a4 a6"),
    )


def test_oled_128x32() -> None:
    bus = FakeI2C()
    Oled("ssd1306", height=32, i2c=bus).open()
    writes = bus.take()
    assert writes[0] == init_sequence("ssd1306", height=32)
    assert writes[1:] == [cmd(0x21, 0, 127, 0x22, 0, 3), dat(bytes(512)), cmd(0xAF)]


def test_oled_rejects_bad_settings() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        Oled("ssd1331", i2c=FakeI2C())
    with pytest.raises(ValueError, match="multiple of 8"):
        Oled("sh1106", height=60, i2c=FakeI2C())


def test_oled_pages_packs_eight_rows_per_byte_lsb_on_top() -> None:
    oled = Oled(i2c=FakeI2C())
    image = Image.new("1", (128, 64))
    for xy in [(0, 0), (5, 7), (10, 9), (127, 63), (64, 32), (64, 33)]:
        image.putpixel(xy, 1)
    data = oled.pages(image)
    assert len(data) == 1024
    assert data[0] == 0x01
    assert data[5] == 0x80
    assert data[128 + 10] == 0x02
    assert data[7 * 128 + 127] == 0x80
    assert data[4 * 128 + 64] == 0x03
    assert sum(1 for byte in data if byte) == 5

    rng = np.random.default_rng(7)
    noise = Image.fromarray(rng.random((64, 128)) > 0.5)
    assert noise.mode == "1"
    assert oled.pages(noise) == reference_pages(noise)
    grey = Image.fromarray((rng.random((64, 128)) > 0.5).astype(np.uint8) * 255)
    assert oled.pages(grey) == reference_pages(grey.convert("1"))
    with pytest.raises(ValueError, match="128x64"):
        oled.pages(Image.new("1", (64, 128)))


@pytest.mark.parametrize("driver", ["sh1106", "ssd1306"])
def test_oled_show_addresses_pages(driver: str) -> None:
    bus = FakeI2C()
    oled = Oled(driver, i2c=bus)
    image = Image.new("1", (128, 64))
    image.paste(1, (0, 0, 8, 8))
    image.putpixel((127, 63), 1)
    oled.show(image)
    writes = bus.take()
    assert writes == frame_writes(driver, reference_pages(image))
    if driver == "sh1106":
        # 132 columns of RAM: the visible 128 start at column 2, one page at a time
        assert writes[:2] == [cmd(0xB0, 0x02, 0x10), dat(bytes([0xFF] * 8 + [0] * 120))]
        assert writes[-2:] == [cmd(0xB7, 0x02, 0x10), dat(bytes(127) + b"\x80")]
    else:
        assert writes[0] == cmd(0x21, 0, 127, 0x22, 0, 7)
        assert len(writes[1]) == 1 + 1024


def test_oled_contrast_power_clear_and_close() -> None:
    bus = FakeI2C()
    oled = Oled("ssd1306", i2c=bus)
    oled.contrast(100)
    oled.contrast(300)
    oled.contrast(-5)
    assert bus.take() == [cmd(0x81, 100), cmd(0x81, 255), cmd(0x81, 0)]
    oled.power(False)
    oled.power(True)
    assert bus.take() == [cmd(0xAE), cmd(0xAF)]
    oled.clear()
    assert bus.take() == frame_writes("ssd1306", bytes(1024))
    oled.close()
    assert bus.take() == [cmd(0xAE)]
    assert bus.closed
    oled.close()
    assert bus.writes == []


def test_oled_uses_smbus2_messages_on_a_real_bus(monkeypatch) -> None:
    buses: list[Any] = []

    class Message:
        @staticmethod
        def write(address: int, buf: bytes) -> tuple[int, bytes]:
            return address, bytes(buf)

    class SMBus:
        def __init__(self, number: int) -> None:
            self.number = number
            self.messages: list[tuple[int, bytes]] = []
            self.closed = False
            buses.append(self)

        def i2c_rdwr(self, *messages: tuple[int, bytes]) -> None:
            self.messages.extend(messages)

        def close(self) -> None:
            self.closed = True

    module = types.ModuleType("smbus2")
    module.SMBus = SMBus  # type: ignore[attr-defined]
    module.i2c_msg = Message  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "smbus2", module)

    oled = Oled("ssd1306", bus=3, width=256, height=64, address=0x3C)
    oled.open()
    (bus,) = buses
    assert bus.number == 3
    assert {address for address, _ in bus.messages} == {0x3C}
    data = [payload for _, payload in bus.messages]
    assert data[0] == init_sequence("ssd1306")
    assert data[1] == cmd(0x21, 0, 255, 0x22, 0, 7)
    # 2048 bytes of pixels go out as two 1024-byte messages, each with its control byte
    assert data[2:] == [dat(bytes(1024)), dat(bytes(1024)), cmd(0xAF)]
    oled.close()
    assert bus.closed


# ---------------------------------------------------------------------------
# WS2812 status LEDs


class FakeSpi:
    def __init__(self, fail: int = 0) -> None:
        self.frames: list[bytes] = []
        self.closed = False
        self.fail = fail

    def writebytes2(self, data: bytes) -> None:
        if self.fail:
            self.fail -= 1
            raise OSError("spi write failed")
        self.frames.append(bytes(data))

    def close(self) -> None:
        self.closed = True


def decode_ws2812(data: bytes, order: str = "GRB") -> list[RGB]:
    """Turn the SPI stream back into pixels: 0b100 is a 0 bit, 0b110 a 1 bit, MSB first."""
    assert data[0] == 0
    body = data[1:].rstrip(b"\x00")  # every encoded byte triple ends in a 1 bit
    assert len(body) % 9 == 0
    reset_seconds = (len(data) - 1 - len(body)) * 8 / SPI_HZ
    assert reset_seconds > 280e-6  # the WS2812 latches after 280 us of low
    values = []
    for i in range(0, len(body), 3):
        word = int.from_bytes(body[i : i + 3], "big")
        value = 0
        for shift in range(21, -1, -3):
            symbol = word >> shift & 0b111
            assert symbol in (0b100, 0b110), f"bad symbol {symbol:03b}"
            value = value << 1 | (symbol == 0b110)
        values.append(value)
    pixels = []
    for i in range(0, len(values), 3):
        channel = dict(zip(order, values[i : i + 3], strict=True))
        pixels.append((channel["R"], channel["G"], channel["B"]))
    return pixels


def test_ws2812_encodes_grb_with_three_spi_bits_per_bit() -> None:
    bit_time = 3 / SPI_HZ
    assert bit_time == pytest.approx(1.25e-6)  # one 800 kHz WS2812 bit
    strip = Ws2812Spi(2, spi=FakeSpi())
    data = strip.encode([(0xFF, 0x00, 0x80), (1, 2, 3)])
    assert data[0] == 0x00  # MOSI low before the first bit
    assert data[1:10] == bytes.fromhex("924924 db6db6 d24924")  # G=0x00, R=0xFF, B=0x80
    assert len(data) == 1 + 2 * 9 + 96
    assert data[-96:] == bytes(96)
    assert decode_ws2812(data) == [(0xFF, 0x00, 0x80), (1, 2, 3)]


def test_ws2812_clamps_values_and_follows_the_color_order() -> None:
    strip = Ws2812Spi(1, spi=FakeSpi())
    assert decode_ws2812(strip.encode([(300, -5, 12.7)])) == [(255, 0, 12)]
    rgb = Ws2812Spi(1, color_order="rgb", spi=FakeSpi())
    assert decode_ws2812(rgb.encode([(10, 20, 30)]), "RGB") == [(10, 20, 30)]
    brg = Ws2812Spi(1, color_order="BRG", spi=FakeSpi())
    data = brg.encode([(10, 20, 30)])
    assert decode_ws2812(data, "BRG") == [(10, 20, 30)]
    assert decode_ws2812(data, "RGB") == [(30, 10, 20)]


def test_ws2812_open_show_and_close(monkeypatch) -> None:
    devices: list[Any] = []

    class SpiDev:
        def __init__(self) -> None:
            self.frames: list[bytes] = []
            self.closed = False
            devices.append(self)

        def open(self, bus: int, device: int) -> None:
            self.opened = (bus, device)

        def writebytes2(self, data: bytes) -> None:
            self.frames.append(bytes(data))

        def close(self) -> None:
            self.closed = True

    module = types.ModuleType("spidev")
    module.SpiDev = SpiDev  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "spidev", module)

    strip = Ws2812Spi(3, bus=1, device=2)
    strip.show([(1, 2, 3)] * 3)  # not open yet: nothing to do
    strip.open()
    (spi,) = devices
    assert (spi.opened, spi.max_speed_hz, spi.mode) == ((1, 2), SPI_HZ, 0)
    strip.show([(255, 0, 0), (0, 255, 0), (0, 0, 255)])
    assert decode_ws2812(spi.frames[-1]) == [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    strip.close()
    assert decode_ws2812(spi.frames[-1]) == [(0, 0, 0)] * 3
    assert spi.closed
    strip.show([(9, 9, 9)] * 3)
    strip.close()
    assert len(spi.frames) == 2


def test_ws2812_close_survives_a_failed_write() -> None:
    spi = FakeSpi(fail=1)
    Ws2812Spi(1, spi=spi).close()
    assert spi.closed


def test_scale() -> None:
    assert scale((255, 128, 10), 0.5) == (127, 64, 5)
    assert scale((255, 255, 255), 0.0) == (0, 0, 0)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (Status.OFF, (0, 0, 0)),
        (Status.IDLE, (0, 0, 25)),
        (Status.LISTENING, (0, 255, 0)),
        (Status.ERROR, (255, 0, 0)),
        (Status.MUTED, (38, 0, 0)),
    ],
)
def test_steady_status_colors(status: Status, expected: RGB) -> None:
    leds = StatusLeds(FakeSpi(), brightness=1.0)
    leds.set(status)
    assert not leds.animating
    assert leds.frame(0.0) == leds.frame(0.3) == expected


@pytest.mark.parametrize(
    ("status", "peak"),
    [
        (Status.THINKING, (0, 255, 255)),
        (Status.SPEAKING, (0, 0, 255)),
        (Status.ALARM, (255, 128, 0)),
    ],
)
def test_pulsing_statuses_breathe_between_ten_and_full_percent(status: Status, peak: RGB) -> None:
    leds = StatusLeds(FakeSpi(), brightness=1.0)
    leds.set(status)
    assert leds.animating
    assert leds.frame(0.4) == peak  # a quarter of the 1.6 s period: brightest
    assert leds.frame(1.2) == scale(peak, 0.1)  # three quarters: dimmest
    assert leds.frame(0.0) == scale(peak, 0.55)
    assert leds.frame(2.0) == peak


def test_brightness_night_and_flash_levels() -> None:
    leds = StatusLeds(FakeSpi(), brightness=0.5)
    leds.set(Status.LISTENING)
    assert leds.frame(0) == (0, 127, 0)
    leds.set_night(True)
    assert leds.frame(0) == (0, 38, 0)
    leds.flash((255, 255, 255), seconds=10)
    assert leds.animating
    assert leds.frame(0) == (38, 38, 38)
    leds.set_night(False)
    leds.flash_volume(50)
    assert leds.frame(0) == (63, 63, 63)
    leds.flash_volume(5)  # never dimmer than 20 %
    assert leds.frame(0) == (25, 25, 25)


class LedRig:
    def __init__(self, count: int = 3, fail: int = 0, **kwargs: Any) -> None:
        self.spi = FakeSpi(fail)
        self.leds = StatusLeds(Ws2812Spi(count, spi=self.spi), **kwargs)

    @property
    def colors(self) -> list[RGB]:
        shown = []
        for frame in self.spi.frames:
            pixels = decode_ws2812(frame)
            assert len(set(pixels)) == 1
            shown.append(pixels[0])
        return shown


@pytest.fixture
async def led_rig():
    rigs: list[LedRig] = []

    def make(**kwargs: Any) -> LedRig:
        new = LedRig(**kwargs)
        new.leds.start()
        rigs.append(new)
        return new

    yield make
    for each in rigs:
        await each.leds.stop()


async def test_status_leds_send_changes_only(led_rig) -> None:
    r = led_rig(brightness=1.0)
    await wait_for(lambda: len(r.spi.frames) == 1)
    assert decode_ws2812(r.spi.frames[0]) == [(0, 0, 0)] * 3
    r.leds.set(Status.LISTENING)
    await wait_for(lambda: len(r.spi.frames) == 2)
    r.leds.set(Status.LISTENING)
    r.leds.set_night(False)
    await asyncio.sleep(0.05)
    assert len(r.spi.frames) == 2
    r.leds.set(Status.ERROR)
    await wait_for(lambda: len(r.spi.frames) == 3)
    assert r.colors == [(0, 0, 0), (0, 255, 0), (255, 0, 0)]
    await r.leds.stop()
    assert r.colors[-1] == (0, 0, 0)
    assert r.spi.closed


async def test_status_leds_animate_pulsing_statuses(led_rig) -> None:
    r = led_rig(brightness=1.0, fps=200)
    r.leds.set(Status.THINKING)
    await wait_for(lambda: len(set(r.colors)) >= 5)
    for red, green, blue in r.colors:
        assert red == 0 and green == blue and 25 <= green <= 255
    r.leds.set(Status.IDLE)
    await wait_for(lambda: r.colors[-1] == (0, 0, 25))
    count = len(r.spi.frames)
    await asyncio.sleep(0.05)
    assert len(r.spi.frames) == count


async def test_status_leds_flash_then_return_to_the_status(led_rig) -> None:
    r = led_rig(brightness=1.0, fps=200)
    r.leds.set(Status.LISTENING)
    await wait_for(lambda: r.colors == [(0, 255, 0)])
    r.leds.flash((255, 255, 255), seconds=0.06)
    await wait_for(lambda: r.colors[-1] == (255, 255, 255))
    await wait_for(lambda: r.colors[-1] == (0, 255, 0), timeout=0.5)
    assert r.colors == [(0, 255, 0), (255, 255, 255), (0, 255, 0)]
    assert not r.leds.animating


async def test_status_leds_night_mode_dims(led_rig) -> None:
    r = led_rig(brightness=1.0)
    r.leds.set(Status.LISTENING)
    await wait_for(lambda: r.colors == [(0, 255, 0)])
    r.leds.set_night(True)
    await wait_for(lambda: r.colors[-1] == (0, 76, 0))
    r.leds.set_night(False)
    await wait_for(lambda: r.colors[-1] == (0, 255, 0))


async def test_status_leds_keep_running_after_a_write_error(led_rig, caplog) -> None:
    r = led_rig(brightness=1.0, fail=1)
    await wait_for(lambda: "Status LEDs failed: spi write failed" in caplog.text)
    r.leds.set(Status.LISTENING)
    await wait_for(lambda: r.colors == [(0, 255, 0)])


# ---------------------------------------------------------------------------
# Volume LED


@pytest.fixture
def pwm_factory():
    factory = MockFactory(pin_class=MockPWMPin)
    yield factory
    factory.close()


def test_volume_led_brightness_follows_the_volume(pwm_factory: MockFactory) -> None:
    led = VolumeLed(12, max_brightness=0.6, pin_factory=pwm_factory)
    pin = pwm_factory.pin(12)
    assert pin.function == "output" and pin.frequency  # driven with PWM
    for level, muted, expected in [(50, False, 0.3), (100, False, 0.6), (0, False, 0.0)]:
        led.show(level, muted)
        assert pin.state == pytest.approx(expected)
        assert led.value == pytest.approx(expected)
    led.show(80, muted=True)
    assert pin.state == 0
    led.night = True
    led.show(100)
    assert pin.state == pytest.approx(0.18)


def test_volume_led_clamps_and_closes(pwm_factory: MockFactory) -> None:
    led = VolumeLed(12, max_brightness=1.5, pin_factory=pwm_factory)
    pin = pwm_factory.pin(12)
    led.show(100)
    assert pin.state == pytest.approx(1.0)
    led.show(-20)
    assert pin.state == 0
    led.show(40)
    assert pin.state == pytest.approx(0.6)
    led.close()
    assert pin.state == 0 and pin.function == "input"
    led.close()
