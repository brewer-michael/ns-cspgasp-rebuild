"""Building a Speaker and its components from the configuration."""

from __future__ import annotations

import asyncio
import contextlib
import socket
import sys
import types
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from datetime import time as dtime

import aiohttp
import pytest
from conftest import make_config
from gpiozero import Device
from gpiozero.pins.mock import MockFactory, MockPWMPin

from open_speaker.agents import AgentChain
from open_speaker.agents.homeassistant import HomeAssistantAgent
from open_speaker.agents.openai_compat import OpenAiAgent
from open_speaker.app import Speaker
from open_speaker.audio.capture import Microphone
from open_speaker.audio.playback import AudioPlayer
from open_speaker.config import Config
from open_speaker.factory import build_speaker
from open_speaker.hardware.buttons import Buttons
from open_speaker.hardware.leds import SPI_HZ, StatusLeds
from open_speaker.hardware.oled import Oled
from open_speaker.hardware.tm1637 import TM1637
from open_speaker.hardware.volume_led import VolumeLed
from open_speaker.homeassistant import HomeAssistant
from open_speaker.pipeline.homeassistant import HomeAssistantPipeline
from open_speaker.pipeline.local import LocalPipeline
from open_speaker.stt.openai_compat import OpenAiStt
from open_speaker.stt.wyoming import WyomingStt
from open_speaker.timers import Scheduler
from open_speaker.tts.openai_compat import OpenAiTts
from open_speaker.tts.wyoming import WyomingTts
from open_speaker.ui import Display, OledRenderer, Tm1637Renderer
from open_speaker.wake.local import MicroWakeWordEngine, OpenWakeWordEngine
from open_speaker.wake.wyoming import WyomingWakeEngine


@dataclass
class Listener:
    """A port on 127.0.0.1 that counts connection attempts."""

    port: int = 0
    connections: int = 0

    @property
    def uri(self) -> str:
        return f"tcp://127.0.0.1:{self.port}"

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@pytest.fixture
async def listener() -> AsyncIterator[Listener]:
    result = Listener()

    async def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        result.connections += 1
        writer.close()

    server = await asyncio.start_server(on_connect, "127.0.0.1", 0)
    result.port = server.sockets[0].getsockname()[1]
    try:
        yield result
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as session:
        yield session


@pytest.fixture
async def build(session: aiohttp.ClientSession) -> AsyncIterator[Callable[[Config], Speaker]]:
    speakers: list[Speaker] = []

    def build(config: Config) -> Speaker:
        speaker = build_speaker(config, session)
        speakers.append(speaker)
        return speaker

    yield build
    for speaker in speakers:
        for coro in speaker.c.extra_tasks:
            coro.close()
        if speaker.c.display is not None:
            await speaker.c.display.stop()
        if speaker.c.leds is not None:
            await speaker.c.leds.stop()
        if speaker.c.volume_led is not None:
            speaker.c.volume_led.close()


@pytest.fixture
def mock_gpio(monkeypatch: pytest.MonkeyPatch) -> Iterator[MockFactory]:
    factory = MockFactory(pin_class=MockPWMPin)
    monkeypatch.setattr(Device, "pin_factory", factory)
    yield factory
    factory.close()


@pytest.fixture
def no_gpio(monkeypatch: pytest.MonkeyPatch) -> None:
    """No GPIO library can be loaded, as on a PC."""
    monkeypatch.setattr(Device, "pin_factory", None)
    monkeypatch.setenv("GPIOZERO_PIN_FACTORY", "unavailable")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ---------------------------------------------------------------------------
# Voice pipelines


async def test_homeassistant_mode(build, tmp_path, listener, session) -> None:
    config = make_config(
        tmp_path, homeassistant={"url": listener.url, "token": "secret", "pipeline": "01jkitchen"}
    )
    speaker = build(config)
    c = speaker.c
    assert speaker.config is config
    assert isinstance(c.mic, Microphone)
    assert c.mic.config is config.audio.input
    assert isinstance(c.player, AudioPlayer)
    assert c.player.config is config.audio.output
    assert isinstance(c.homeassistant, HomeAssistant)
    assert (c.homeassistant.url, c.homeassistant.token) == (listener.url, "secret")
    assert isinstance(c.pipeline, HomeAssistantPipeline)
    assert (c.pipeline.ha, c.pipeline.pipeline_id, c.pipeline.vad) == (
        c.homeassistant,
        "01jkitchen",
        config.vad,
    )
    assert isinstance(c.scheduler, Scheduler)
    assert (c.scheduler.state_file, c.scheduler.missed_grace) == (config.timers_state_file, 600)
    assert (speaker.mic, speaker.player, speaker.pipeline, speaker.scheduler) == (
        c.mic,
        c.player,
        c.pipeline,
        c.scheduler,
    )
    assert c.session is session
    # The no-hardware config: no wake word engine, display, LEDs or HTTP API.
    assert speaker.wake is None
    assert c.wake is None
    assert c.display is None
    assert c.leds is None
    assert c.volume_led is None
    assert c.extra_tasks == []
    await asyncio.sleep(0.05)
    assert listener.connections == 0


async def test_local_mode_with_wyoming_servers(build, tmp_path, listener) -> None:
    config = make_config(
        tmp_path,
        homeassistant={"url": listener.url},
        pipeline={"mode": "local"},
        stt={"engine": "wyoming", "uri": listener.uri, "language": "en"},
        tts={"engine": "wyoming", "uri": listener.uri, "voice": "en_US-lessac-medium"},
        agents=[
            {"engine": "homeassistant", "agent_id": "conversation.ollama"},
            {"engine": "openai", "url": f"{listener.url}/v1", "model": "llama3.2"},
        ],
        wake={"engine": "wyoming", "uri": listener.uri, "names": ["ok_nabu"]},
    )
    speaker = build(config)
    pipeline = speaker.pipeline
    assert isinstance(pipeline, LocalPipeline)
    assert isinstance(pipeline.stt, WyomingStt)
    assert pipeline.stt.uri == listener.uri
    assert pipeline.stt_language == "en"
    assert isinstance(pipeline.tts, WyomingTts)
    assert (pipeline.tts.uri, pipeline.tts.voice) == (listener.uri, "en_US-lessac-medium")
    assert isinstance(pipeline.agents, AgentChain)
    home, model = pipeline.agents.agents
    assert isinstance(home, HomeAssistantAgent)
    assert (home.homeassistant, home.agent_id) == (speaker.c.homeassistant, "conversation.ollama")
    assert isinstance(model, OpenAiAgent)
    assert (model.endpoint, model.model) == (f"{listener.url}/v1/chat/completions", "llama3.2")
    assert isinstance(speaker.wake, WyomingWakeEngine)
    assert (speaker.wake.uri, speaker.wake.names) == (listener.uri, ["ok_nabu"])
    await asyncio.sleep(0.05)
    assert listener.connections == 0


async def test_local_mode_with_openai_servers_and_no_home_assistant(
    build, tmp_path, listener, session
) -> None:
    url = f"{listener.url}/v1"
    config = make_config(
        tmp_path,
        homeassistant={"url": None, "token": None},
        pipeline={"mode": "local"},
        stt={"engine": "openai", "url": url, "model": "whisper-small"},
        tts={"engine": "openai", "url": url, "voice": "af_heart"},
        agents=[{"engine": "openai", "url": url, "model": "llama3.2", "api_key": "sk-local"}],
    )
    speaker = build(config)
    assert speaker.c.homeassistant is None
    pipeline = speaker.pipeline
    assert isinstance(pipeline, LocalPipeline)
    assert isinstance(pipeline.stt, OpenAiStt)
    assert (pipeline.stt.endpoint, pipeline.stt.model) == (
        f"{url}/audio/transcriptions",
        "whisper-small",
    )
    assert isinstance(pipeline.tts, OpenAiTts)
    assert (pipeline.tts.endpoint, pipeline.tts.voice) == (f"{url}/audio/speech", "af_heart")
    (agent,) = pipeline.agents.agents
    assert isinstance(agent, OpenAiAgent)
    assert (agent.api_key, agent.session) == ("sk-local", session)
    await asyncio.sleep(0.05)
    assert listener.connections == 0


@pytest.mark.parametrize(
    ("wake", "engine"),
    [
        ({"engine": "none"}, type(None)),
        ({"engine": "microwakeword", "model": "hey_jarvis"}, MicroWakeWordEngine),
        ({"engine": "openwakeword", "model": "hey_rhasspy"}, OpenWakeWordEngine),
        ({"engine": "wyoming", "uri": "tcp://127.0.0.1:10400"}, WyomingWakeEngine),
    ],
)
async def test_wake_word_engines(build, tmp_path, wake, engine) -> None:
    speaker = build(make_config(tmp_path, wake=wake))
    assert type(speaker.wake) is engine
    assert speaker.c.wake is speaker.wake


async def test_timers_can_be_turned_off(build, tmp_path) -> None:
    assert build(make_config(tmp_path, timers={"enabled": False})).scheduler is None


async def test_timer_state_file_and_grace_period(build, tmp_path) -> None:
    state_file = tmp_path / "elsewhere" / "timers.json"
    config = make_config(
        tmp_path, timers={"state_file": str(state_file), "missed_grace_seconds": 60}
    )
    scheduler = build(config).scheduler
    assert (scheduler.state_file, scheduler.missed_grace) == (state_file, 60)


# ---------------------------------------------------------------------------
# Hardware


async def test_oled_display(build, tmp_path) -> None:
    config = make_config(
        tmp_path,
        display={
            "type": "oled",
            "clock_24h": True,
            "night_start": "23:30",
            "oled": {"driver": "ssd1306", "address": 0x3D, "contrast": 200, "pixel_shift": False},
        },
    )
    speaker = build(config)
    display = speaker.c.display
    assert isinstance(display, Display)
    assert display.state == speaker.display_state
    assert display.on_night == speaker.on_night
    assert (display.night_start, display.night_end) == (dtime(23, 30), dtime(7, 0))
    assert display.state().clock_24h
    renderer = display.renderer
    assert isinstance(renderer, OledRenderer)
    assert (renderer.contrast, renderer.night_contrast, renderer.pixel_shift) == (200, 8, False)
    assert isinstance(renderer.device, Oled)  # the I2C bus opens when the display starts
    assert (renderer.device.driver, renderer.device.address) == ("ssd1306", 0x3D)


async def test_tm1637_display(build, tmp_path, mock_gpio) -> None:
    config = make_config(
        tmp_path,
        display={"type": "tm1637", "tm1637": {"brightness": 5, "night_brightness": 1}},
    )
    display = build(config).c.display
    assert isinstance(display, Display)
    assert isinstance(display.renderer, Tm1637Renderer)
    assert isinstance(display.renderer.device, TM1637)
    assert (display.renderer.brightness, display.renderer.night_brightness) == (5, 1)


async def test_status_leds_and_volume_led(build, tmp_path, mock_gpio, monkeypatch) -> None:
    opened: list[tuple[int, int, int]] = []

    class SpiDev:
        max_speed_hz = 0

        def open(self, bus: int, device: int) -> None:
            opened.append((bus, device, self.max_speed_hz))

        def writebytes2(self, data: bytes) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setitem(sys.modules, "spidev", types.SimpleNamespace(SpiDev=SpiDev))
    config = make_config(
        tmp_path,
        status_leds={"type": "ws2812", "count": 5, "brightness": 0.5},
        volume_led={"pin": 12, "max_brightness": 0.4},
    )
    speaker = build(config)
    leds = speaker.c.leds
    assert isinstance(leds, StatusLeds)
    assert (leds.brightness, leds.strip.count) == (0.5, 5)
    assert opened == [(0, 0, 0)]
    assert leds.strip._spi.max_speed_hz == SPI_HZ
    assert isinstance(speaker.c.volume_led, VolumeLed)
    assert speaker.c.volume_led.max_brightness == 0.4


async def test_missing_hardware_is_left_out(build, tmp_path, no_gpio, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "spidev", None)  # py-spidev is not installed
    config = make_config(
        tmp_path,
        display={"type": "tm1637"},
        status_leds={"type": "ws2812"},
        volume_led={"pin": 12},
    )
    speaker = build(config)
    assert speaker.c.display is None
    assert speaker.c.leds is None
    assert speaker.c.volume_led is None
    assert isinstance(speaker.c.buttons, Buttons)  # GPIO is needed only once they start


async def test_buttons(build, tmp_path) -> None:
    buttons = build(make_config(tmp_path)).c.buttons
    assert isinstance(buttons, Buttons)
    assert buttons.pins == {"volume_up": 17, "volume_down": 27, "mute": 22, "action": 5}
    assert (buttons.long_press, buttons.repeat_delay, buttons.repeat_interval) == (0.8, 0.3, 0.1)
    config = make_config(tmp_path, buttons={"mute": None, "action": 6, "long_press_seconds": 1.5})
    buttons = build(config).c.buttons
    assert buttons.pins == {"volume_up": 17, "volume_down": 27, "action": 6}
    assert buttons.long_press == 1.5
    none = {"volume_up": None, "volume_down": None, "mute": None, "action": None}
    assert build(make_config(tmp_path, buttons=none)).c.buttons is None


# ---------------------------------------------------------------------------
# HTTP API


async def test_api_is_served_only_when_enabled(build, tmp_path, session) -> None:
    assert build(make_config(tmp_path, api={"enabled": False})).c.extra_tasks == []

    port = free_port()
    config = make_config(
        tmp_path, api={"enabled": True, "host": "127.0.0.1", "port": port, "token": "t0ken"}
    )
    speaker = build(config)
    (serve,) = speaker.c.extra_tasks
    url = f"http://127.0.0.1:{port}/api/status"
    with pytest.raises(aiohttp.ClientConnectionError):  # nothing listens before it runs
        await session.get(url)
    task = asyncio.create_task(serve)
    try:
        deadline = asyncio.get_running_loop().time() + 5
        while True:
            try:
                async with session.get(url, headers={"Authorization": "Bearer t0ken"}) as resp:
                    status, body = resp.status, await resp.json()
                break
            except aiohttp.ClientConnectionError:
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.01)
        assert (status, body["name"], body["state"]) == (200, "Open Speaker", "idle")
        async with session.get(url) as resp:
            assert resp.status == 401
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    with pytest.raises(aiohttp.ClientConnectionError):  # cancelling the task stops the server
        await session.get(url)
