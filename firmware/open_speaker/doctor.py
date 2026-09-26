"""``open-speaker doctor``: checks the things that usually go wrong on a new build."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import aiohttp

from .config import Config, ConfigError, load_config
from .const import SAMPLE_RATE

OK, WARN, FAIL = "ok", "warn", "fail"
_SYMBOL = {OK: "✔", WARN: "!", FAIL: "✖"}


class Report:
    def __init__(self) -> None:
        self.results: list[tuple[str, str, str]] = []

    def add(self, status: str, title: str, detail: str = "") -> None:
        self.results.append((status, title, detail))
        line = f" {_SYMBOL[status]} {title}"
        print(line + (f": {detail}" if detail else ""), flush=True)

    @property
    def failures(self) -> int:
        return sum(1 for status, _, _ in self.results if status == FAIL)


async def _output(*argv: str) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
    except OSError as err:
        return 127, str(err)
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace")


async def wyoming_describe(uri: str, timeout: float = 5.0) -> Any:
    from wyoming.client import AsyncClient
    from wyoming.info import Describe, Info

    client = AsyncClient.from_uri(uri, connect_timeout=timeout)
    await client.connect()
    try:
        await client.write_event(Describe().event())
        while True:
            event = await asyncio.wait_for(client.read_event(), timeout)
            if event is None:
                raise ConnectionError("connection closed")
            if Info.is_type(event.type):
                return Info.from_event(event)
    finally:
        await client.disconnect()


def _program_names(info: Any, domain: str) -> str:
    programs = getattr(info, domain, []) or []
    names = [p.name for p in programs]
    models = [m.name for p in programs for m in (getattr(p, "models", None) or [])]
    voices = [v.name for p in programs for v in (getattr(p, "voices", None) or [])]
    extra = models or voices
    return ", ".join(names) + (f" ({', '.join(extra[:5])})" if extra else "")


async def _check_tools(config: Config, report: Report) -> None:
    decoder = config.audio.output.decoder.split()[0]
    for tool, package in (
        ("arecord", "alsa-utils"),
        ("aplay", "alsa-utils"),
        ("amixer", "alsa-utils"),
        (decoder, decoder),
    ):
        if shutil.which(tool):
            report.add(OK, f"{tool} installed")
        else:
            report.add(FAIL, f"{tool} missing", f"sudo apt install {package}")


async def _check_audio_devices(config: Config, report: Report) -> None:
    code, cards = await _output("aplay", "-l")
    if code == 0:
        names = [line for line in cards.splitlines() if line.startswith("card ")]
        known = [n for n in names if "googlevoi" in n.lower() or "max98357" in n.lower()]
        if known:
            report.add(OK, "I2S sound card", known[0])
        elif names:
            report.add(WARN, "I2S sound card not found", "cards: " + "; ".join(names))
        else:
            report.add(FAIL, "No playback devices", "check dtoverlay in /boot/firmware/config.txt")
    code, pcms = await _output("arecord", "-L")
    device = config.audio.input.device
    if code == 0 and device not in ("default",) and device not in pcms.split():
        report.add(
            WARN,
            f"Capture device {device!r} not listed by arecord -L",
            "was /etc/asound.conf installed? (scripts/install.sh does this)",
        )


async def _check_microphone(config: Config, report: Report) -> None:
    from .audio.capture import Microphone
    from .audio.pcm import rms_dbfs

    mic = Microphone(config.audio.input)
    audio = bytearray()

    async def record() -> None:
        async for chunk in mic.chunks():
            audio.extend(chunk)
            if len(audio) >= SAMPLE_RATE * 2:  # one second
                return

    try:
        await asyncio.wait_for(record(), 5)
    except TimeoutError:
        report.add(FAIL, "Microphone", "no audio within 5 s (see the service log for errors)")
        return
    finally:
        await mic.close()
    level = rms_dbfs(bytes(audio))
    if level < -85:
        report.add(FAIL, "Microphone", "digital silence: check SD->GPIO20, L/R pins and 3.3 V")
    elif level < -65:
        report.add(WARN, "Microphone", f"very quiet ({level:.0f} dBFS); try audio.input.gain_db")
    else:
        report.add(OK, "Microphone", f"room level {level:.0f} dBFS")


async def _check_wake(config: Config, report: Report) -> None:
    wake = config.wake
    if wake.engine == "none":
        report.add(WARN, "Wake word disabled", "only the action button starts listening")
        return
    if wake.engine == "wyoming":
        try:
            info = await wyoming_describe(str(wake.uri))
            report.add(OK, f"Wake word server {wake.uri}", _program_names(info, "wake"))
        except (OSError, TimeoutError, ConnectionError) as err:
            report.add(FAIL, f"Wake word server {wake.uri}", str(err))
        return
    from .wake import create_wake_engine

    engine = create_wake_engine(wake)
    assert engine is not None
    try:
        await engine.start()
        report.add(OK, f"Wake word ({wake.engine})", engine.name)
    except Exception as err:
        report.add(FAIL, f"Wake word ({wake.engine})", f"{err} (pip install '.[pi]')")
    finally:
        await engine.stop()


async def _check_homeassistant(
    config: Config, session: aiohttp.ClientSession, report: Report
) -> None:
    from .factory import create_homeassistant
    from .homeassistant import HomeAssistantError

    ha = create_homeassistant(config, session)
    if ha is None:
        return
    try:
        await ha.check()
        await ha.connect()
        report.add(OK, "Home Assistant", f"{config.homeassistant.url} (version {ha.version})")
        if config.pipeline.mode == "homeassistant":
            result = await ha.command({"type": "assist_pipeline/pipeline/list"})
            pipelines = {p["id"]: p for p in (result or {}).get("pipelines", [])}
            preferred = (result or {}).get("preferred_pipeline")
            wanted = config.homeassistant.pipeline or preferred
            pipeline = pipelines.get(wanted or "")
            if pipeline is None:
                report.add(FAIL, "Assist pipeline", f"{wanted!r} not found")
            else:
                detail = (
                    f"{pipeline.get('name')}: stt={pipeline.get('stt_engine')}, "
                    f"agent={pipeline.get('conversation_engine')}, tts={pipeline.get('tts_engine')}"
                )
                status = OK if pipeline.get("stt_engine") else FAIL
                report.add(status, "Assist pipeline", detail)
            # the ids to use for homeassistant.pipeline in the configuration
            for pid, item in pipelines.items():
                mark = " (preferred)" if pid == preferred else ""
                print(f"     {pid}  {item.get('name')}{mark}", flush=True)
        entity = config.display.temperature.entity
        if entity:
            state = await ha.get_state(entity)
            report.add(OK if state else FAIL, f"Temperature entity {entity}",
                       f"state {state.get('state')!r}" if state else "not found")  # fmt: skip
    except HomeAssistantError as err:
        report.add(FAIL, "Home Assistant", str(err))
    finally:
        await ha.close()


async def _check_openai(
    session: aiohttp.ClientSession, report: Report, title: str, url: str, api_key: str | None,
    model: str | None,
) -> None:  # fmt: skip
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with session.get(
            url.rstrip("/") + "/models", headers=headers, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status != 200:
                report.add(WARN, title, f"{url}/models returned HTTP {response.status}")
                return
            data = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError) as err:
        report.add(FAIL, title, f"cannot reach {url}: {err}")
        return
    models = [m.get("id") for m in (data.get("data") or []) if isinstance(m, dict)]
    if model and models and model not in models:
        report.add(WARN, title, f"model {model!r} not in {models[:8]}")
    else:
        report.add(OK, title, url)


async def _check_local_servers(
    config: Config, session: aiohttp.ClientSession, report: Report
) -> None:
    for kind, section in (("Speech-to-text", config.stt), ("Text-to-speech", config.tts)):
        if section.engine == "wyoming":
            try:
                info = await wyoming_describe(str(section.uri))
                domain = "asr" if kind == "Speech-to-text" else "tts"
                report.add(OK, f"{kind} {section.uri}", _program_names(info, domain))
            except (OSError, TimeoutError, ConnectionError) as err:
                report.add(FAIL, f"{kind} {section.uri}", str(err))
        else:
            await _check_openai(
                session, report, kind, str(section.url), section.api_key, section.model
            )
    for i, agent in enumerate(config.agents):
        if agent.engine == "openai":
            await _check_openai(
                session, report, f"Agent {i} ({agent.model})", str(agent.url), agent.api_key,
                agent.model,
            )  # fmt: skip


def _check_hardware(config: Config, report: Report) -> None:
    display = config.display
    if display.type == "oled":
        bus = f"/dev/i2c-{display.oled.i2c_bus}"
        if not Path(bus).exists():
            report.add(FAIL, "OLED display", f"{bus} missing: add dtparam=i2c_arm=on")
        else:
            try:
                from smbus2 import SMBus

                with SMBus(display.oled.i2c_bus) as smbus:
                    smbus.read_byte(display.oled.address)
                report.add(OK, "OLED display", f"found at 0x{display.oled.address:02X}")
            except ImportError:
                report.add(FAIL, "OLED display", "smbus2 not installed")
            except OSError:
                address = f"0x{display.oled.address:02X}"
                report.add(FAIL, "OLED display", f"nothing at {address}; run i2cdetect -y 1")
    if config.status_leds.type == "ws2812":
        spi = f"/dev/spidev{config.status_leds.spi_bus}.{config.status_leds.spi_device}"
        if Path(spi).exists():
            report.add(OK, "Status LEDs", spi)
        else:
            report.add(FAIL, "Status LEDs", f"{spi} missing: add dtparam=spi=on")
    if display.type == "tm1637" or any(
        p is not None
        for p in (config.buttons.volume_up, config.buttons.volume_down, config.buttons.mute,
                  config.buttons.action, config.volume_led.pin)
    ):  # fmt: skip
        chips = sorted(str(p) for p in Path("/dev").glob("gpiochip*"))
        if chips:
            report.add(OK, "GPIO", ", ".join(chips))
        else:
            report.add(FAIL, "GPIO", "no /dev/gpiochip* (not a Raspberry Pi?)")


def _check_state_dir(config: Config, report: Report) -> None:
    path = Path(config.state_dir)
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path):
            pass
        report.add(OK, "State directory", str(path))
    except OSError as err:
        report.add(
            FAIL, "State directory", f"{path} not writable ({err}); running as {os.getuid()}"
        )


async def run_doctor(config_path: Path) -> int:
    report = Report()
    print("Open Speaker doctor\n")
    try:
        config = load_config(config_path)
        report.add(OK, "Configuration", str(config_path))
    except ConfigError as err:
        report.add(FAIL, "Configuration", str(err))
        return 1

    await _check_tools(config, report)
    await _check_audio_devices(config, report)
    await _check_microphone(config, report)
    await _check_wake(config, report)
    async with aiohttp.ClientSession() as session:
        await _check_homeassistant(config, session, report)
        if config.pipeline.mode == "local":
            await _check_local_servers(config, session, report)
    _check_hardware(config, report)
    _check_state_dir(config, report)

    print(f"\n{report.failures} problem(s) found." if report.failures else "\nAll checks passed.")
    return 1 if report.failures else 0
