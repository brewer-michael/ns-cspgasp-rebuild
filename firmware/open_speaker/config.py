"""Configuration: a YAML file mapped onto typed dataclasses, with validation.

Every option has a default that matches the reference build (see
``hardware/schematics/gpio_pinout.md``), so a minimal config only needs the
Home Assistant URL and token, or the addresses of your local inference servers.
String values may reference environment variables as ``${NAME}`` or
``${NAME:-default}``, which keeps secrets out of the file (the systemd unit loads
them from ``/etc/open-speaker/secrets.env``).
"""

from __future__ import annotations

import dataclasses
import os
import re
import types
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

import yaml

from .const import DEFAULT_API_PORT, DEFAULT_STATE_DIR, I2C_PINS, I2S_PINS, I2S_RESERVED_PINS

SECRET_FIELDS = frozenset({"token", "api_key"})


class ConfigError(ValueError):
    """The configuration file is missing, malformed or inconsistent."""


# ---------------------------------------------------------------------------
# Schema


@dataclass
class InputConfig:
    """Microphone capture (an external recorder that writes raw PCM to stdout)."""

    command: str = "arecord -q -D {device} -r {rate} -c {channels} -f S16_LE -t raw"
    device: str = "mics"
    channels: int = 2
    # Which captured channel to use: 0 (left mic), 1 (right mic) or "mix" (average).
    channel: int | Literal["mix"] = "mix"
    gain_db: float = 0.0
    samples_per_chunk: int = 512


@dataclass
class OutputConfig:
    """Speaker playback (an external player that reads raw PCM from stdin)."""

    command: str = "aplay -q -D {device} -r {rate} -c {channels} -f S16_LE -t raw"
    device: str = "default"
    # Decodes compressed speech (Home Assistant sends MP3 by default). mpg123 is tiny,
    # which matters on a Pi Zero 2 W; for OGG/FLAC use
    # "ffmpeg -hide_banner -loglevel error -i pipe:0 -f s16le -ac 1 -ar {rate} pipe:1".
    decoder: str = "mpg123 -q -s -m -r {rate} -"
    decode_rate: int = 48000
    # ALSA mixer control that holds the system volume. The installer creates a
    # "Master" softvol control; set to null to scale samples in software instead.
    volume_control: str | None = "Master"
    mixer_card: str | None = None
    # Optional second softvol control (e.g. "Music") that is lowered while the
    # assistant is listening or speaking.
    duck_control: str | None = None
    duck_volume: int = 20
    # Loudness of beeps and alarms relative to speech (0-1).
    sound_volume: float = 0.6


@dataclass
class AudioConfig:
    input: InputConfig = field(default_factory=InputConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    initial_volume: int = 50
    volume_step: int = 5


@dataclass
class WakeConfig:
    engine: Literal["microwakeword", "openwakeword", "wyoming", "none"] = "microwakeword"
    # Built-in model name (okay_nabu, hey_jarvis, hey_mycroft, alexa; openwakeword
    # also has hey_rhasspy) or a path to a model file.
    model: str = "okay_nabu"
    threshold: float | None = None
    uri: str | None = None
    names: list[str] = field(default_factory=list)
    refractory_seconds: float = 2.0


@dataclass
class VadConfig:
    """End-of-speech detection for the local pipeline."""

    engine: Literal["energy", "microvad"] = "energy"
    threshold: float = 0.5
    energy_margin_db: float = 10.0
    energy_min_dbfs: float = -55.0
    speech_start_timeout: float = 5.0
    min_speech_seconds: float = 0.25
    silence_seconds: float = 0.8
    max_seconds: float = 15.0


@dataclass
class PipelineConfig:
    # homeassistant: speech-to-text, the conversation agent and text-to-speech run in
    # a Home Assistant Assist pipeline. local: the speaker calls your inference
    # servers directly (see the stt, agents and tts sections).
    mode: Literal["homeassistant", "local"] = "homeassistant"
    follow_up: bool = True
    local_intents: bool = True


@dataclass
class HomeAssistantConfig:
    url: str | None = None
    token: str | None = None
    pipeline: str | None = None
    verify_ssl: bool = True
    timeout: float = 30.0


@dataclass
class SttConfig:
    engine: Literal["wyoming", "openai"] = "wyoming"
    uri: str | None = None
    url: str | None = None
    api_key: str | None = None
    model: str | None = None
    language: str | None = None
    timeout: float = 30.0


@dataclass
class TtsConfig:
    engine: Literal["wyoming", "openai"] = "wyoming"
    uri: str | None = None
    url: str | None = None
    api_key: str | None = None
    model: str | None = None
    voice: str | None = None
    speaker: str | None = None
    speed: float | None = None
    response_format: str = "wav"
    timeout: float = 30.0


@dataclass
class AgentConfig:
    engine: Literal["homeassistant", "openai"] = "homeassistant"
    # homeassistant: conversation agent id, e.g. conversation.ollama (default agent if unset)
    agent_id: str | None = None
    # openai: any OpenAI-compatible server such as Ollama, llama.cpp, vLLM or LocalAI
    url: str | None = None
    api_key: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    temperature: float | None = 0.5
    max_tokens: int | None = 300
    history_turns: int = 6
    history_timeout: float = 300.0
    timeout: float = 30.0


@dataclass
class TimersConfig:
    enabled: bool = True
    state_file: str | None = None
    ring_timeout: float = 120.0
    snooze_minutes: int = 9
    # Alarms and timers that came due while the speaker was off still ring if they
    # were missed by less than this many seconds.
    missed_grace_seconds: float = 600.0


@dataclass
class OledConfig:
    driver: Literal["sh1106", "ssd1306", "ssd1309"] = "sh1106"
    i2c_bus: int = 1
    address: int = 0x3C
    width: int = 128
    height: int = 64
    rotate: Literal[0, 180] = 0
    contrast: int = 180
    night_contrast: int = 8
    # Moves the picture by a pixel or two every few minutes to limit OLED burn-in.
    pixel_shift: bool = True
    font: str | None = None


@dataclass
class Tm1637Config:
    clk_pin: int = 23
    dio_pin: int = 24
    brightness: int = 3
    night_brightness: int = 0


@dataclass
class TemperatureConfig:
    # Home Assistant entity: a sensor (uses its state) or a weather entity (uses its
    # temperature attribute).
    entity: str | None = None
    refresh_seconds: float = 300.0
    unit: str | None = None


@dataclass
class DisplayConfig:
    type: Literal["oled", "tm1637", "none"] = "oled"
    clock_24h: bool = False
    night_start: str | None = "22:00"
    night_end: str | None = "07:00"
    oled: OledConfig = field(default_factory=OledConfig)
    tm1637: Tm1637Config = field(default_factory=Tm1637Config)
    temperature: TemperatureConfig = field(default_factory=TemperatureConfig)


@dataclass
class StatusLedConfig:
    type: Literal["ws2812", "none"] = "ws2812"
    count: int = 3
    spi_bus: int = 0
    spi_device: int = 0
    brightness: float = 0.3
    color_order: str = "GRB"


@dataclass
class VolumeLedConfig:
    pin: int | None = 12
    max_brightness: float = 0.6


@dataclass
class ButtonsConfig:
    volume_up: int | None = 17
    volume_down: int | None = 27
    mute: int | None = 22
    action: int | None = 5
    # What the mute button silences: the microphones (privacy) or the speaker.
    mute_function: Literal["microphone", "speaker"] = "microphone"
    long_press_seconds: float = 0.8
    repeat_delay: float = 0.3
    repeat_interval: float = 0.1
    bounce_seconds: float = 0.05


@dataclass
class SoundsConfig:
    """Earcons: "builtin:<name>", a path to a WAV file, or null to disable."""

    wake: str | None = "builtin:wake"
    done: str | None = "builtin:done"
    error: str | None = "builtin:error"
    alarm: str | None = "builtin:alarm"
    timer: str | None = "builtin:timer"
    volume: str | None = "builtin:volume"


@dataclass
class ApiConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = DEFAULT_API_PORT
    token: str | None = None


@dataclass
class Config:
    name: str = "Open Speaker"
    language: str = "en"
    log_level: str = "INFO"
    state_dir: str = DEFAULT_STATE_DIR
    audio: AudioConfig = field(default_factory=AudioConfig)
    wake: WakeConfig = field(default_factory=WakeConfig)
    vad: VadConfig = field(default_factory=VadConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    homeassistant: HomeAssistantConfig = field(default_factory=HomeAssistantConfig)
    stt: SttConfig = field(default_factory=SttConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)
    agents: list[AgentConfig] = field(default_factory=lambda: [AgentConfig()])
    timers: TimersConfig = field(default_factory=TimersConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    status_leds: StatusLedConfig = field(default_factory=StatusLedConfig)
    volume_led: VolumeLedConfig = field(default_factory=VolumeLedConfig)
    buttons: ButtonsConfig = field(default_factory=ButtonsConfig)
    sounds: SoundsConfig = field(default_factory=SoundsConfig)
    api: ApiConfig = field(default_factory=ApiConfig)

    @property
    def timers_state_file(self) -> Path:
        if self.timers.state_file:
            return Path(self.timers.state_file)
        return Path(self.state_dir) / "timers.json"

    @property
    def settings_file(self) -> Path:
        return Path(self.state_dir) / "settings.json"


# ---------------------------------------------------------------------------
# Loading


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand_env(value: Any, path: str) -> Any:
    if isinstance(value, dict):
        return {k: _expand_env(v, f"{path}.{k}" if path else str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v, f"{path}[{i}]") for i, v in enumerate(value)]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        if name in os.environ:
            return os.environ[name]
        if default is not None:
            return default
        raise ConfigError(f"{path}: environment variable {name} is not set")

    expanded = _ENV_PATTERN.sub(replace, value)
    # "${UNSET:-}" means "no value"
    return None if expanded == "" and _ENV_PATTERN.fullmatch(value) else expanded


def _type_name(tp: Any) -> str:
    return getattr(tp, "__name__", str(tp))


def _convert(tp: Any, value: Any, path: str) -> Any:
    origin = get_origin(tp)

    if origin in (Union, types.UnionType):
        args = get_args(tp)
        if value is None:
            if type(None) in args:
                return None
            raise ConfigError(f"{path}: a value is required")
        for arg in args:
            if arg is type(None):
                continue
            try:
                return _convert(arg, value, path)
            except ConfigError:
                continue
        expected = " or ".join(_describe(a) for a in args if a is not type(None))
        raise ConfigError(f"{path}: expected {expected}, got {value!r}")

    if origin is Literal:
        for choice in get_args(tp):
            if value == choice and type(value) is type(choice):
                return choice
        raise ConfigError(f"{path}: must be one of {_describe(tp)}, got {value!r}")

    if origin is list:
        if not isinstance(value, list):
            raise ConfigError(f"{path}: expected a list, got {value!r}")
        (item_type,) = get_args(tp)
        return [_convert(item_type, item, f"{path}[{i}]") for i, item in enumerate(value)]

    if is_dataclass(tp):
        return _build(tp, value, path)

    if tp is bool:
        if isinstance(value, bool):
            return value
    elif tp is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    elif tp is float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    elif tp is str:
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    elif tp is Any:
        return value
    else:  # pragma: no cover - schema bug
        raise ConfigError(f"{path}: unsupported option type {_type_name(tp)}")

    raise ConfigError(f"{path}: expected {_describe(tp)}, got {value!r}")


def _describe(tp: Any) -> str:
    if get_origin(tp) is Literal:
        return ", ".join(repr(c) for c in get_args(tp))
    return {bool: "true/false", int: "an integer", float: "a number", str: "a string"}.get(
        tp, _type_name(tp)
    )


def _build(cls: type, data: Any, path: str) -> Any:
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path or 'config'}: expected a mapping, got {data!r}")

    hints = get_type_hints(cls)
    names = {f.name for f in fields(cls)}
    unknown = sorted(str(k) for k in data if k not in names)
    if unknown:
        where = f"{path}." if path else ""
        raise ConfigError(f"unknown option(s): {', '.join(where + k for k in unknown)}")

    kwargs = {
        name: _convert(hints[name], value, f"{path}.{name}" if path else name)
        for name, value in data.items()
    }
    return cls(**kwargs)


def config_from_dict(data: dict[str, Any] | None) -> Config:
    """Build and validate a :class:`Config` from already-parsed YAML data."""
    config = _build(Config, _expand_env(data or {}, ""), "")
    validate(config)
    return config


def load_config(path: str | Path) -> Config:
    """Read, parse and validate a YAML configuration file."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as err:
        raise ConfigError(f"configuration file not found: {path}") from err
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as err:
        raise ConfigError(f"{path}: invalid YAML: {err}") from err
    if data is not None and not isinstance(data, dict):
        raise ConfigError(f"{path}: the top level must be a mapping")
    return config_from_dict(data)


def config_to_dict(config: Config, redact: bool = True) -> dict[str, Any]:
    """The effective configuration as plain data, with secrets masked."""

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: ("***" if redact and k in SECRET_FIELDS and v else scrub(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value

    return scrub(dataclasses.asdict(config))


# ---------------------------------------------------------------------------
# Validation


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _check_uri(uri: str | None, path: str, errors: list[str]) -> None:
    if not uri:
        errors.append(f"{path} is required (e.g. tcp://192.168.1.10:10300)")
    elif not uri.startswith(("tcp://", "unix://")):
        errors.append(f"{path} must start with tcp:// or unix://, got {uri!r}")


def _check_url(url: str | None, path: str, errors: list[str]) -> None:
    if not url:
        errors.append(f"{path} is required (e.g. http://192.168.1.10:8000/v1)")
    elif not url.startswith(("http://", "https://")):
        errors.append(f"{path} must start with http:// or https://, got {url!r}")


def _check_clock(value: str | None, path: str, errors: list[str]) -> None:
    if value is None:
        return
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        errors.append(f"{path} must be a 24-hour time like 22:00, got {value!r}")


def used_pins(config: Config) -> dict[int, str]:
    """GPIO pins claimed by the configured hardware, mapped to what uses them."""
    claims: list[tuple[int, str]] = []
    buttons = config.buttons
    for name in ("volume_up", "volume_down", "mute", "action"):
        pin = getattr(buttons, name)
        if pin is not None:
            claims.append((pin, f"buttons.{name}"))
    if config.volume_led.pin is not None:
        claims.append((config.volume_led.pin, "volume_led.pin"))
    if config.display.type == "tm1637":
        claims.append((config.display.tm1637.clk_pin, "display.tm1637.clk_pin"))
        claims.append((config.display.tm1637.dio_pin, "display.tm1637.dio_pin"))

    seen: dict[int, str] = {}
    duplicates: list[str] = []
    for pin, who in claims:
        if pin in seen:
            duplicates.append(f"GPIO{pin} ({seen[pin]} and {who})")
        else:
            seen[pin] = who
    if duplicates:
        raise ConfigError("GPIO pins used twice: " + "; ".join(duplicates))
    return seen


def validate(config: Config) -> None:
    """Raise :class:`ConfigError` describing every problem found."""
    errors: list[str] = []
    ha = config.homeassistant
    ha_configured = bool(ha.url and ha.token)

    if ha.url:
        _check_url(ha.url, "homeassistant.url", errors)

    if config.pipeline.mode == "homeassistant":
        _require(
            ha_configured,
            "pipeline.mode is homeassistant, so homeassistant.url and homeassistant.token "
            "are required",
            errors,
        )
    else:
        stt, tts = config.stt, config.tts
        if stt.engine == "wyoming":
            _check_uri(stt.uri, "stt.uri", errors)
        else:
            _check_url(stt.url, "stt.url", errors)
        if tts.engine == "wyoming":
            _check_uri(tts.uri, "tts.uri", errors)
        else:
            _check_url(tts.url, "tts.url", errors)
        _require(bool(config.agents), "agents: at least one agent is required", errors)
        for i, agent in enumerate(config.agents):
            if agent.engine == "homeassistant":
                _require(
                    ha_configured,
                    f"agents[{i}] uses Home Assistant, so homeassistant.url and "
                    "homeassistant.token are required",
                    errors,
                )
            else:
                _check_url(agent.url, f"agents[{i}].url", errors)
                _require(bool(agent.model), f"agents[{i}].model is required", errors)

    wake = config.wake
    if wake.engine == "wyoming":
        _check_uri(wake.uri, "wake.uri", errors)
    elif wake.engine != "none":
        _require(bool(wake.model), "wake.model is required", errors)
    if wake.threshold is not None:
        _require(0 < wake.threshold < 1, "wake.threshold must be between 0 and 1", errors)

    audio = config.audio
    _require(0 <= audio.initial_volume <= 100, "audio.initial_volume must be 0-100", errors)
    _require(1 <= audio.volume_step <= 50, "audio.volume_step must be 1-50", errors)
    _require(audio.input.channels >= 1, "audio.input.channels must be at least 1", errors)
    channel = audio.input.channel
    if isinstance(channel, int):
        _require(
            0 <= channel < audio.input.channels,
            f"audio.input.channel must be 'mix' or 0-{audio.input.channels - 1}",
            errors,
        )
    _require(audio.input.samples_per_chunk >= 160, "audio.input.samples_per_chunk >= 160", errors)
    _require(0 <= audio.output.duck_volume <= 100, "audio.output.duck_volume must be 0-100", errors)
    _require(0 < audio.output.sound_volume <= 1, "audio.output.sound_volume must be 0-1", errors)

    vad = config.vad
    _require(vad.silence_seconds > 0, "vad.silence_seconds must be positive", errors)
    _require(vad.max_seconds > vad.silence_seconds, "vad.max_seconds is too small", errors)

    display = config.display
    _check_clock(display.night_start, "display.night_start", errors)
    _check_clock(display.night_end, "display.night_end", errors)
    _require(0 <= display.oled.contrast <= 255, "display.oled.contrast must be 0-255", errors)
    _require(
        0 <= display.oled.night_contrast <= 255, "display.oled.night_contrast must be 0-255", errors
    )
    _require(0 <= display.tm1637.brightness <= 7, "display.tm1637.brightness must be 0-7", errors)
    _require(0 < config.status_leds.brightness <= 1, "status_leds.brightness must be 0-1", errors)
    _require(config.status_leds.count >= 1, "status_leds.count must be at least 1", errors)
    _require(
        sorted(config.status_leds.color_order.upper()) == ["B", "G", "R"],
        "status_leds.color_order must be a permutation of RGB",
        errors,
    )
    _require(1 <= config.api.port <= 65535, "api.port must be 1-65535", errors)
    _require(config.timers.snooze_minutes >= 1, "timers.snooze_minutes must be at least 1", errors)

    try:
        pins = used_pins(config)
    except ConfigError as err:
        errors.append(str(err))
        pins = {}
    reserved = {pin: "I2S audio" for pin in I2S_PINS}
    reserved.update({pin: "the I2S amplifier driver (SD_MODE)" for pin in I2S_RESERVED_PINS})
    if display.type == "oled":
        reserved.update({pin: "the OLED display (I2C)" for pin in I2C_PINS})
    if config.status_leds.type == "ws2812" and config.status_leds.spi_bus == 0:
        reserved.update({pin: "the status LEDs (SPI0)" for pin in (7, 8, 9, 10, 11)})
    for pin, who in pins.items():
        if not 0 <= pin <= 27:
            errors.append(f"{who}: GPIO{pin} does not exist on the 40-pin header")
        elif pin in reserved:
            errors.append(f"{who}: GPIO{pin} is already used by {reserved[pin]}")

    if errors:
        raise ConfigError("invalid configuration:\n  - " + "\n  - ".join(errors))
