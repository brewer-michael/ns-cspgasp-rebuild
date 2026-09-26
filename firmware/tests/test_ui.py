"""The display: clock helpers, the OLED and TM1637 renderers and the Display loop."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from datetime import datetime
from datetime import time as dtime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from conftest import wait_for
from gpiozero.pins.mock import MockFactory

from open_speaker import ui
from open_speaker.hardware.oled import Oled
from open_speaker.hardware.tm1637 import TM1637
from open_speaker.ui import (
    Display,
    DisplayState,
    OledRenderer,
    Renderer,
    Tm1637Renderer,
    blink_on,
    clock_digits,
    format_countdown,
    is_night,
    parse_clock,
)

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
needs_font = pytest.mark.skipif(not Path(FONT).is_file(), reason="needs DejaVu Sans Bold")


def at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 3, 14, hour, minute, second)


# ---------------------------------------------------------------------------
# Helpers


def test_parse_clock() -> None:
    assert parse_clock("22:00") == dtime(22, 0)
    assert parse_clock("7:05") == dtime(7, 5)
    assert parse_clock(None) is None
    assert parse_clock("") is None


@pytest.mark.parametrize(
    ("now", "night"),
    [
        (at(21, 59), False),
        (at(22, 0), True),
        (at(23, 59), True),
        (at(0, 0), True),
        (at(3, 30), True),
        (at(6, 59), True),
        (at(7, 0), False),
        (at(12, 0), False),
    ],
)
def test_is_night_across_midnight(now: datetime, night: bool) -> None:
    assert is_night(now, dtime(22, 0), dtime(7, 0)) is night


@pytest.mark.parametrize(
    ("now", "night"),
    [(at(12, 59), False), (at(13, 0), True), (at(14, 59), True), (at(15, 0), False)],
)
def test_is_night_within_one_day(now: datetime, night: bool) -> None:
    assert is_night(now, dtime(13, 0), dtime(15, 0)) is night


def test_is_night_needs_a_window() -> None:
    assert not is_night(at(23, 0), None, dtime(7, 0))
    assert not is_night(at(23, 0), dtime(22, 0), None)
    assert not is_night(at(23, 0), dtime(22, 0), dtime(22, 0))


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "0:00"),
        (0.2, "0:01"),  # partial seconds round up, so 0:00 only shows when it is over
        (59, "0:59"),
        (59.5, "1:00"),
        (90, "1:30"),
        (3599, "59:59"),
        (3600, "1:00:00"),
        (3661, "1:01:01"),
        (36000, "10:00:00"),
        (-5, "0:00"),
    ],
)
def test_format_countdown(seconds: float, text: str) -> None:
    assert format_countdown(seconds) == text


@pytest.mark.parametrize(
    ("now", "clock_24h", "expected"),
    [
        (at(0, 5), False, ("12:05", "AM")),
        (at(7, 42), False, ("7:42", "AM")),
        (at(12, 0), False, ("12:00", "PM")),
        (at(19, 42), False, ("7:42", "PM")),
        (at(23, 59), False, ("11:59", "PM")),
        (at(0, 5), True, ("00:05", None)),
        (at(7, 42), True, ("07:42", None)),
        (at(19, 42), True, ("19:42", None)),
    ],
)
def test_clock_digits(now: datetime, clock_24h: bool, expected: tuple[str, str | None]) -> None:
    assert clock_digits(now, clock_24h) == expected


def test_blink_on_even_seconds() -> None:
    assert [blink_on(at(8, 0, s)) for s in range(4)] == [True, False, True, False]


# ---------------------------------------------------------------------------
# OLED renderer

Box = tuple[int, int, int, int]  # x0, y0, x1, y1 (exclusive)
AL_BOX: Box = (0, 0, 22, 18)
MERIDIEM_BOX: Box = (0, 18, 22, 34)
TIME_BOX: Box = (22, 0, 128, 34)
SECONDARY_BOX: Box = (0, 36, 128, 64)


class FakeOledDevice:
    """A 128x64 display that packs pages like the real driver and records what it is sent."""

    width = 128
    height = 64

    def __init__(self) -> None:
        self._packer = Oled(i2c=object())
        self.calls: list[str] = []
        self.contrasts: list[int] = []
        self.frames: list[bytes] = []

    def open(self) -> None:
        self.calls.append("open")

    def close(self) -> None:
        self.calls.append("close")

    def pages(self, image: Any) -> bytes:
        return self._packer.pages(image)

    def contrast(self, value: int) -> None:
        self.contrasts.append(value)

    def show_bytes(self, data: bytes) -> None:
        self.frames.append(data)


def oled(pixel_shift: bool = False, **kwargs: Any) -> OledRenderer:
    return OledRenderer(FakeOledDevice(), pixel_shift=pixel_shift, font=FONT, **kwargs)


def pixels(renderer: OledRenderer, state: DisplayState) -> np.ndarray:
    image = renderer.draw(state)
    assert image.size == (128, 64) and image.mode == "1"
    return np.asarray(image, dtype=bool)


def lit(a: np.ndarray, box: Box) -> int:
    x0, y0, x1, y1 = box
    return int(a[y0:y1, x0:x1].sum())


def only_in(a: np.ndarray, box: Box) -> bool:
    return a.any() and lit(a, box) == int(a.sum())


def extent(a: np.ndarray, box: Box = (0, 0, 128, 64)) -> Box:
    """Inclusive bounds of the lit pixels inside ``box``."""
    x0, y0, x1, y1 = box
    ys, xs = np.nonzero(a[y0:y1, x0:x1])
    return int(xs.min()) + x0, int(ys.min()) + y0, int(xs.max()) + x0, int(ys.max()) + y0


@needs_font
def test_oled_clock_screen_layout() -> None:
    a = pixels(oled(), DisplayState(now=at(19, 42), alarm_set=True, secondary="72°F"))
    assert lit(a, AL_BOX) and lit(a, MERIDIEM_BOX)
    assert not a[34:36].any()
    left, top, right, bottom = extent(a, TIME_BOX)
    assert top == 3 and 120 <= right <= 125 and bottom < 34
    assert right - left > 60  # large digits
    left, top, right, _ = extent(a, SECONDARY_BOX)
    assert top == 43 and 120 <= right <= 125 and left > 64  # right-aligned under the time


@needs_font
def test_oled_alarm_marker_is_drawn_top_left() -> None:
    r = oled()
    state = DisplayState(now=at(19, 42), secondary="72°F")
    diff = pixels(r, replace(state, alarm_set=True)) ^ pixels(r, state)
    assert only_in(diff, AL_BOX)


@needs_font
def test_oled_am_pm_marker_is_drawn_left_of_the_time() -> None:
    r = oled()
    am, pm = pixels(r, DisplayState(now=at(7, 42))), pixels(r, DisplayState(now=at(19, 42)))
    assert lit(am, MERIDIEM_BOX) and lit(pm, MERIDIEM_BOX)
    assert only_in(am ^ pm, MERIDIEM_BOX)
    h24 = pixels(r, DisplayState(now=at(19, 42), clock_24h=True))
    assert only_in(h24, TIME_BOX)
    assert not h24[:, :22].any()


@needs_font
def test_oled_time_is_right_aligned_with_minutes_last() -> None:
    r = oled()
    diff = pixels(r, DisplayState(now=at(19, 42))) ^ pixels(r, DisplayState(now=at(19, 43)))
    assert only_in(diff, (96, 0, 128, 34))
    five = pixels(r, DisplayState(now=at(0, 5)))  # "12:05" is set a little smaller to fit
    seven = pixels(r, DisplayState(now=at(7, 42)))
    assert np.array_equal(five[:, :22], seven[:, :22])  # only the AM marker left of the time
    assert extent(five, TIME_BOX)[2] <= 125


@needs_font
def test_oled_swapped_value_replaces_the_secondary_slot() -> None:
    r = oled()
    state = DisplayState(now=at(19, 42), secondary="72°F")
    temperature = pixels(r, state)
    volume = pixels(r, replace(state, secondary="Vol 60", swap=True))
    assert only_in(temperature ^ volume, SECONDARY_BOX)
    assert only_in(temperature ^ pixels(r, replace(state, secondary=None)), SECONDARY_BOX)
    assert np.array_equal(temperature[:34], volume[:34])


@needs_font
def test_oled_mode_takes_over_the_whole_screen() -> None:
    r = oled()
    net = pixels(r, DisplayState(now=at(19, 42), alarm_set=True, secondary="72°F", mode="net"))
    assert np.array_equal(net, pixels(r, DisplayState(now=at(7, 5), mode="net")))
    left, top, right, bottom = extent(net)
    assert abs((left + right) / 2 - 63.5) <= 2
    assert abs((top + bottom) / 2 - 31.5) <= 2
    assert bottom - top >= 20  # large type
    assert not lit(net, AL_BOX) and not lit(net, MERIDIEM_BOX)


@needs_font
def test_oled_ringing_alarm_blinks_the_clock() -> None:
    r = oled()
    state = DisplayState(now=at(6, 30, 10), alarm_set=True, secondary="68°F", ringing="alarm")
    on = pixels(r, state)
    off = pixels(r, replace(state, now=at(6, 30, 11)))
    assert np.array_equal(on, pixels(r, replace(state, ringing=None)))
    assert not lit(off, TIME_BOX) and not lit(off, AL_BOX) and not lit(off, MERIDIEM_BOX)
    assert np.array_equal(off[34:], on[34:])  # the secondary value stays


@needs_font
def test_oled_ringing_timer_blinks_the_secondary_slot() -> None:
    r = oled()
    state = DisplayState(now=at(6, 30, 10), secondary="End", ringing="timer")
    on = pixels(r, state)
    off = pixels(r, replace(state, now=at(6, 30, 11)))
    assert lit(on, SECONDARY_BOX) and not lit(off, SECONDARY_BOX)
    assert np.array_equal(on[:34], off[:34])  # the time stays


@needs_font
@pytest.mark.parametrize(
    ("now", "shift"),
    [
        (at(0, 0), (0, 0)),
        (at(0, 2), (0, 0)),
        (at(0, 3), (1, 0)),
        (at(0, 5), (1, 0)),
        (at(0, 6), (1, 1)),
        (at(0, 9), (0, 1)),
        (at(0, 12), (-1, 1)),
        (at(0, 15), (-1, 0)),
        (at(0, 18), (-1, -1)),
        (at(0, 21), (0, -1)),
        (at(0, 24), (1, -1)),
        (at(0, 27), (0, 0)),
        (at(1, 0), (1, 1)),
    ],
)
def test_oled_pixel_shift_moves_everything_by_a_pixel(
    now: datetime, shift: tuple[int, int]
) -> None:
    dx, dy = shift
    for state in (
        DisplayState(now=now, alarm_set=True, secondary="72°F"),
        DisplayState(now=now, mode="net"),
    ):
        still = pixels(oled(pixel_shift=False), state)
        moved = pixels(oled(pixel_shift=True), state)
        assert np.array_equal(moved, np.roll(still, (dy, dx), axis=(0, 1)))


@needs_font
def test_oled_render_sends_changed_frames_and_night_contrast() -> None:
    r = oled(contrast=200, night_contrast=5)
    device = r.device
    r.open()
    state = DisplayState(now=at(19, 42), secondary="72°F")
    r.render(state, night=False)
    assert device.contrasts == [200]
    assert device.frames == [device.pages(r.draw(state))]
    r.render(state, night=False)
    assert device.contrasts == [200] and len(device.frames) == 1
    r.render(state, night=True)  # same picture, dimmer
    assert device.contrasts == [200, 5] and len(device.frames) == 1
    later = replace(state, now=at(19, 43))
    r.render(later, night=True)
    assert device.contrasts == [200, 5]
    assert device.frames[1:] == [device.pages(r.draw(later))]
    r.render(later, night=False)
    assert device.contrasts == [200, 5, 200] and len(device.frames) == 2
    r.close()
    assert device.calls == ["open", "close"]


@needs_font
def test_oled_render_resends_blinking_frames() -> None:
    r = oled()
    ringing = DisplayState(now=at(6, 30, 0), secondary="68°F", ringing="alarm")
    for second in (0, 2, 3, 5, 6):
        r.render(replace(ringing, now=at(6, 30, second)), night=False)
    frames = r.device.frames
    assert len(frames) == 3  # 2 looks like 0 and 5 like 3, so they are not sent again
    assert frames[0] == frames[2] != frames[1]


def test_oled_font_falls_back_to_pillows_default(monkeypatch) -> None:
    monkeypatch.setattr(ui, "FONT_CANDIDATES", ())
    r = OledRenderer(FakeOledDevice(), font="/nonexistent/font.ttf")
    assert r.font(18) is r.font(18)
    assert pixels(r, DisplayState(now=at(7, 5), secondary="72°F")).any()


@needs_font
def test_oled_uses_the_configured_font() -> None:
    regular = str(Path(FONT).with_name("DejaVuSans.ttf"))
    assert OledRenderer(FakeOledDevice(), font=regular).font(11).path == regular
    assert OledRenderer(FakeOledDevice()).font(11).path == FONT


# ---------------------------------------------------------------------------
# TM1637 renderer


class FakeTm1637:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def brightness(self, level: int) -> None:
        self.calls.append(("brightness", level))

    def show(self, text: str, colon: bool = False) -> None:
        self.calls.append(("show", text, colon))

    def close(self) -> None:
        self.calls.append(("close",))

    def take(self) -> list[tuple[Any, ...]]:
        calls, self.calls = self.calls, []
        return calls


def shown(renderer: Tm1637Renderer, state: DisplayState, night: bool = False) -> Any:
    renderer.device.take()
    renderer.render(state, night)
    return renderer.device.take()


@pytest.fixture
def tm() -> Tm1637Renderer:
    renderer = Tm1637Renderer(FakeTm1637(), brightness=3, night_brightness=0)
    renderer.render(DisplayState(now=at(3, 33, 33), mode="----"), night=False)
    renderer.device.take()
    return renderer


def test_tm1637_time_with_blinking_colon(tm: Tm1637Renderer) -> None:
    assert shown(tm, DisplayState(now=at(19, 42, 0))) == [("show", " 742", True)]
    assert shown(tm, DisplayState(now=at(19, 42, 1))) == [("show", " 742", False)]
    assert shown(tm, DisplayState(now=at(19, 42, 3))) == []  # unchanged
    assert shown(tm, DisplayState(now=at(0, 5, 2))) == [("show", "1205", True)]
    assert shown(tm, DisplayState(now=at(19, 42, 2), clock_24h=True)) == [("show", "1942", True)]
    assert shown(tm, DisplayState(now=at(7, 5, 4), clock_24h=True)) == [("show", "0705", True)]


def test_tm1637_swapped_volume_shows_straight_away(tm: Tm1637Renderer) -> None:
    state = DisplayState(now=at(19, 42, 0), secondary="Vol 45", swap=True)
    assert shown(tm, state) == [("show", " V45", False)]
    assert shown(tm, replace(state, secondary="Vol 100")) == [("show", "V100", False)]
    assert shown(tm, replace(state, secondary="mic off")) == [("show", " off", False)]


def test_tm1637_temperature_takes_turns_with_the_time(tm: Tm1637Renderer) -> None:
    state = DisplayState(now=at(19, 42, 6), secondary="72°F")
    assert shown(tm, state) == [("show", " 742", True)]
    for second in (7, 8, 9):
        tm.render(replace(state, now=at(19, 42, second)), night=False)
    assert tm.device.take() == [("show", " 72°", False)]
    assert shown(tm, replace(state, now=at(19, 42, 10))) == [("show", " 742", True)]
    minus = replace(state, now=at(19, 42, 17), secondary="\u22123°C")
    assert shown(tm, minus) == [("show", " -3°", False)]
    no_value = DisplayState(now=at(19, 42, 18))
    assert shown(tm, no_value) == [("show", " 742", True)]


def test_tm1637_countdown_keeps_its_colon(tm: Tm1637Renderer) -> None:
    state = DisplayState(now=at(19, 42, 8), secondary="4:05")
    assert shown(tm, state) == [("show", " 405", True)]
    assert shown(tm, replace(state, secondary="12:34")) == [("show", "1234", True)]


def test_tm1637_ringing_timer_flashes_end(tm: Tm1637Renderer) -> None:
    state = DisplayState(now=at(6, 30, 0), secondary="End", ringing="timer")
    assert shown(tm, state) == [("show", " End", False)]
    assert shown(tm, replace(state, now=at(6, 30, 1))) == [("show", "    ", False)]


def test_tm1637_ringing_alarm_flashes_the_time(tm: Tm1637Renderer) -> None:
    state = DisplayState(now=at(6, 30, 0), ringing="alarm", alarm_set=True)
    assert shown(tm, state) == [("show", " 630", True)]
    assert shown(tm, replace(state, now=at(6, 30, 1))) == [("show", "    ", False)]


def test_tm1637_mode_takes_over(tm: Tm1637Renderer) -> None:
    state = DisplayState(now=at(6, 30, 1), mode="net", ringing="timer", secondary="End")
    assert shown(tm, state) == [("show", "net ", False)]
    assert shown(tm, replace(state, mode="pairing")) == [("show", "pair", False)]


def test_tm1637_night_brightness() -> None:
    renderer = Tm1637Renderer(FakeTm1637(), brightness=5, night_brightness=1)
    device = renderer.device
    renderer.open()
    assert device.take() == [("brightness", 5)]
    state = DisplayState(now=at(23, 15, 0), clock_24h=True)
    renderer.render(state, night=True)
    assert device.take() == [("brightness", 1), ("show", "2315", True)]
    renderer.render(state, night=True)
    assert device.take() == []
    renderer.render(state, night=False)
    assert device.take() == [("brightness", 5)]
    renderer.close()
    assert device.take() == [("close",)]


def test_tm1637_renderer_drives_the_real_display() -> None:
    factory = MockFactory()
    renderer = Tm1637Renderer(TM1637(pin_factory=factory))
    renderer.render(DisplayState(now=at(19, 42, 0)), night=False)
    assert renderer.device.last_segments == [0x00, 0x07 | 0x80, 0x66, 0x5B]  # " 7:42"
    renderer.render(DisplayState(now=at(19, 42, 0), secondary="Vol 45", swap=True), night=False)
    assert renderer.device.last_segments == [0x00, 0x3E, 0x66, 0x6D]  # " V45"
    renderer.close()
    assert renderer.device.last_segments == [0, 0, 0, 0]
    factory.close()


# ---------------------------------------------------------------------------
# Display controller


class FakeRenderer(Renderer):
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.threads: set[str] = set()
        self.hold: threading.Event | None = None
        self.error: Exception | None = None

    def _record(self, *call: Any) -> None:
        self.calls.append(call)
        self.threads.add(threading.current_thread().name)

    def open(self) -> None:
        self._record("open")

    def render(self, state: DisplayState, night: bool) -> None:
        self._record("render", state, night)
        if self.error is not None:
            raise self.error
        hold, self.hold = self.hold, None
        if hold is not None:
            hold.wait(2)

    def close(self) -> None:
        self._record("close")

    @property
    def renders(self) -> list[tuple[Any, ...]]:
        return [call for call in self.calls if call[0] == "render"]


def freeze_clock(monkeypatch, microsecond: int) -> None:
    """Pin where the display loop thinks it is within the current second."""

    class Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return datetime(2026, 3, 14, 12, 0, 0, microsecond)

    monkeypatch.setattr(ui, "datetime", Clock)


async def test_display_draws_on_start_and_on_refresh(monkeypatch) -> None:
    freeze_clock(monkeypatch, 0)  # the next second boundary is a full second away
    renderer = FakeRenderer()
    state = DisplayState(now=at(12, 0))
    display = Display(renderer, lambda: state)
    await display.start()
    try:
        await wait_for(lambda: len(renderer.renders) == 1)
        assert renderer.calls == [("open",), ("render", state, False)]
        assert all(name.startswith("display") for name in renderer.threads)
        display.refresh()
        await wait_for(lambda: len(renderer.renders) == 2, timeout=0.5)
        await asyncio.sleep(0.2)
        assert len(renderer.renders) == 2
    finally:
        await display.stop()
    assert renderer.calls[-1] == ("close",)
    display.refresh()
    await asyncio.sleep(0.05)
    assert len(renderer.renders) == 2


async def test_display_redraws_at_each_second_boundary(monkeypatch) -> None:
    freeze_clock(monkeypatch, 990_000)  # 10 ms before the next second
    renderer = FakeRenderer()
    display = Display(renderer, lambda: DisplayState(now=at(12, 0)))
    await display.start()
    try:
        await wait_for(lambda: len(renderer.renders) >= 4, timeout=0.9)
    finally:
        await display.stop()


async def test_display_reports_night_changes(monkeypatch) -> None:
    freeze_clock(monkeypatch, 0)
    events: list[tuple[str, bool]] = []
    current = [DisplayState(now=at(21, 59))]

    class Recorder(FakeRenderer):
        def render(self, state: DisplayState, night: bool) -> None:
            events.append(("render", night))
            super().render(state, night)

    renderer = Recorder()
    display = Display(
        renderer,
        lambda: current[0],
        night_start="22:00",
        night_end="07:00",
        on_night=lambda night: events.append(("on_night", night)),
    )
    await display.start()
    try:
        await wait_for(lambda: len(renderer.renders) == 1)
        for count, now in enumerate([at(22, 0), at(23, 30), at(7, 0)], start=2):
            current[0] = DisplayState(now=now)
            display.refresh()
            await wait_for(lambda count=count: len(renderer.renders) == count, timeout=0.5)
    finally:
        await display.stop()
    assert events == [
        ("render", False),
        ("on_night", True),
        ("render", True),
        ("render", True),
        ("on_night", False),
        ("render", False),
    ]
    assert display.night is False


async def test_display_refresh_during_a_draw_is_not_lost(monkeypatch) -> None:
    freeze_clock(monkeypatch, 0)
    renderer = FakeRenderer()
    current = [DisplayState(now=at(12, 0), secondary="72°F")]
    display = Display(renderer, lambda: current[0])
    gate = threading.Event()
    await display.start()
    try:
        await wait_for(lambda: len(renderer.renders) == 1)
        renderer.hold = gate
        display.refresh()
        await wait_for(lambda: len(renderer.renders) == 2)
        # The volume changes while the previous state is still being drawn.
        current[0] = DisplayState(now=at(12, 0), secondary="Vol 60", swap=True)
        display.refresh()
        gate.set()
        await wait_for(lambda: len(renderer.renders) == 3, timeout=0.5)
        assert renderer.renders[2][1] == current[0]
    finally:
        gate.set()
        await display.stop()


async def test_display_survives_render_errors(monkeypatch, caplog) -> None:
    freeze_clock(monkeypatch, 0)
    renderer = FakeRenderer()
    renderer.error = OSError("I2C bus error")
    display = Display(renderer, lambda: DisplayState(now=at(12, 0)))
    await display.start()
    await wait_for(lambda: "Display update failed: I2C bus error" in caplog.text)
    await asyncio.wait_for(display.stop(), 1)
    assert renderer.calls[-1] == ("close",)
