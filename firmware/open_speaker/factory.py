"""Builds a :class:`Speaker` with real components from a :class:`Config`."""

from __future__ import annotations

import logging

import aiohttp

from .agents import create_agents
from .app import Components, Speaker
from .audio.capture import Microphone
from .audio.playback import AudioPlayer
from .config import Config
from .homeassistant import HomeAssistant
from .pipeline import Pipeline
from .timers import Scheduler
from .wake import create_wake_engine

_LOGGER = logging.getLogger(__name__)


async def _noop_ring(_ring: object) -> None:
    return None


def create_homeassistant(config: Config, session: aiohttp.ClientSession) -> HomeAssistant | None:
    ha = config.homeassistant
    if not (ha.url and ha.token):
        return None
    return HomeAssistant(ha.url, ha.token, session, verify_ssl=ha.verify_ssl, timeout=ha.timeout)


def create_pipeline(
    config: Config, session: aiohttp.ClientSession, homeassistant: HomeAssistant | None
) -> Pipeline:
    if config.pipeline.mode == "homeassistant":
        from .pipeline.homeassistant import HomeAssistantPipeline

        assert homeassistant is not None
        return HomeAssistantPipeline(homeassistant, config.vad, config.homeassistant.pipeline)

    from .pipeline.local import LocalPipeline
    from .stt import create_stt
    from .tts import create_tts

    return LocalPipeline(
        create_stt(config.stt, session),
        create_agents(config.agents, session, homeassistant),
        create_tts(config.tts, session),
        config.vad,
        stt_language=config.stt.language,
    )


def _optional(what: str, factory):  # type: ignore[no-untyped-def]
    try:
        return factory()
    except Exception as err:  # hardware missing, not wired, or not a Pi
        _LOGGER.warning("%s unavailable: %s", what, err)
        return None


def create_display(config: Config):  # type: ignore[no-untyped-def]
    display = config.display
    if display.type == "oled":
        from .hardware.oled import Oled
        from .ui import OledRenderer

        oled = display.oled
        device = Oled(
            oled.driver,
            oled.i2c_bus,
            oled.address,
            oled.width,
            oled.height,
            oled.rotate,
            oled.contrast,
        )
        return OledRenderer(
            device,
            contrast=oled.contrast,
            night_contrast=oled.night_contrast,
            pixel_shift=oled.pixel_shift,
            font=oled.font,
        )
    if display.type == "tm1637":
        from .hardware.tm1637 import TM1637
        from .ui import Tm1637Renderer

        tm = display.tm1637
        return Tm1637Renderer(TM1637(tm.clk_pin, tm.dio_pin), tm.brightness, tm.night_brightness)
    return None


def create_leds(config: Config):  # type: ignore[no-untyped-def]
    leds = config.status_leds
    if leds.type != "ws2812":
        return None
    from .hardware.leds import StatusLeds, Ws2812Spi

    strip = Ws2812Spi(leds.count, leds.spi_bus, leds.spi_device, leds.color_order)
    strip.open()
    return StatusLeds(strip, leds.brightness)


def create_buttons(config: Config):  # type: ignore[no-untyped-def]
    from .hardware.buttons import Buttons

    b = config.buttons
    pins = {
        name: pin
        for name, pin in (
            ("volume_up", b.volume_up),
            ("volume_down", b.volume_down),
            ("mute", b.mute),
            ("action", b.action),
        )
        if pin is not None
    }
    if not pins:
        return None
    return Buttons(
        pins,
        on_event=lambda *_: None,
        long_press=b.long_press_seconds,
        repeat_delay=b.repeat_delay,
        repeat_interval=b.repeat_interval,
        bounce=b.bounce_seconds,
    )


def build_speaker(config: Config, session: aiohttp.ClientSession) -> Speaker:
    from .ui import Display

    homeassistant = create_homeassistant(config, session)
    scheduler = None
    if config.timers.enabled:
        scheduler = Scheduler(
            config.timers_state_file,
            on_ring=_noop_ring,
            missed_grace_seconds=config.timers.missed_grace_seconds,
        )
    volume_led = None
    if config.volume_led.pin is not None:
        from .hardware.volume_led import VolumeLed

        pin = config.volume_led.pin
        volume_led = _optional(
            "Volume LED", lambda: VolumeLed(pin, config.volume_led.max_brightness)
        )

    components = Components(
        mic=Microphone(config.audio.input),
        player=AudioPlayer(config.audio.output),
        pipeline=create_pipeline(config, session, homeassistant),
        wake=create_wake_engine(config.wake),
        homeassistant=homeassistant,
        scheduler=scheduler,
        leds=_optional("Status LEDs", lambda: create_leds(config)),
        volume_led=volume_led,
        buttons=_optional("Buttons", lambda: create_buttons(config)),
        session=session,
    )
    speaker = Speaker(config, components)

    renderer = _optional("Display", lambda: create_display(config))
    if renderer is not None:
        components.display = Display(
            renderer,
            speaker.display_state,
            config.display.night_start,
            config.display.night_end,
            on_night=speaker.on_night,
        )

    if config.api.enabled:
        from .api import serve

        components.extra_tasks.append(serve(speaker, config.api))
    return speaker
