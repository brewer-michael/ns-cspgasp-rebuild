"""Configuration: YAML onto typed dataclasses, environment variables and validation."""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Iterator
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from conftest import make_config

from open_speaker.config import (
    AgentConfig,
    AudioConfig,
    Config,
    ConfigError,
    DisplayConfig,
    HomeAssistantConfig,
    InputConfig,
    SttConfig,
    TimersConfig,
    TtsConfig,
    config_from_dict,
    config_to_dict,
    load_config,
    used_pins,
    validate,
)

HA: dict[str, Any] = {"homeassistant": {"url": "http://ha.test:8123", "token": "secret"}}
LLM: dict[str, Any] = {"engine": "openai", "url": "http://10.0.0.2:11434/v1", "model": "llama3.2"}
LOCAL: dict[str, Any] = {
    "pipeline": {"mode": "local"},
    "stt": {"uri": "tcp://10.0.0.2:10300"},
    "tts": {"uri": "tcp://10.0.0.2:10200"},
    "agents": [LLM],
}
HA_REQUIRED = (
    "pipeline.mode is homeassistant, so homeassistant.url and homeassistant.token are required"
)


def build(**sections: Any) -> Config:
    """The reference build (all defaults) with Home Assistant set up, plus ``sections``."""
    return config_from_dict({**HA, **sections})


def problems(data: dict[str, Any] | None) -> list[str]:
    """Every problem reported for ``data``."""
    with pytest.raises(ConfigError) as err:
        config_from_dict(data)
    message = str(err.value)
    if message.startswith("invalid configuration:"):
        return message.split("\n  - ")[1:]
    return [message]


def nested(path: str, value: Any) -> dict[str, Any]:
    for key in reversed(path.split(".")):
        value = {key: value}
    return value


def lookup(config: Any, path: str) -> Any:
    for key in path.split("."):
        config = getattr(config, key)
    return config


@contextlib.contextmanager
def example_config() -> Iterator[Path]:
    """The example that ships with the package (``open-speaker`` copies it on install)."""
    example = resources.files("open_speaker").joinpath("data/config.example.yaml")
    with resources.as_file(example) as path:
        yield path


# ---------------------------------------------------------------------------
# Defaults


@pytest.mark.parametrize("data", [{}, None])
def test_an_empty_config_only_lacks_home_assistant(data: dict[str, Any] | None) -> None:
    assert problems(data) == [HA_REQUIRED]


def test_defaults() -> None:
    config = config_from_dict(HA)
    assert config == Config(homeassistant=HomeAssistantConfig("http://ha.test:8123", "secret"))
    assert config.pipeline.mode == "homeassistant"
    assert (config.wake.engine, config.wake.model) == ("microwakeword", "okay_nabu")
    assert config.audio.input.channel == "mix"
    assert config.agents == [AgentConfig()]
    assert config.display.type == "oled"
    assert config.status_leds.type == "ws2812"
    buttons = config.buttons
    assert (buttons.volume_up, buttons.volume_down, buttons.mute, buttons.action) == (17, 27, 22, 5)
    assert config.api.port == 10800
    assert config.timers_state_file == Path("/var/lib/open-speaker/timers.json")
    assert config.settings_file == Path("/var/lib/open-speaker/settings.json")


def test_the_default_config_object_validates() -> None:
    validate(Config(homeassistant=HomeAssistantConfig("http://ha.test:8123", "secret")))
    with pytest.raises(ConfigError, match=re.escape(HA_REQUIRED)):
        validate(Config())


def test_empty_sections_are_defaults() -> None:
    config = build(audio=None, display=None, timers=None)
    assert config.audio == AudioConfig()
    assert config.display == DisplayConfig()
    assert config.timers == TimersConfig()


def test_a_partial_section_keeps_the_other_defaults() -> None:
    config = build(audio={"volume_step": 10, "input": {"device": "hw:1"}})
    assert config.audio == AudioConfig(input=InputConfig(device="hw:1"), volume_step=10)


def test_state_paths(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    assert config.timers_state_file == tmp_path / "state" / "timers.json"
    assert config.settings_file == tmp_path / "state" / "settings.json"
    moved = make_config(tmp_path, timers={"state_file": str(tmp_path / "alarms.json")})
    assert moved.timers_state_file == tmp_path / "alarms.json"


# ---------------------------------------------------------------------------
# Environment variables


def test_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OS_TEST_HOST", "10.0.0.5")
    monkeypatch.setenv("OS_TEST_TOKEN", "from-env")
    config = config_from_dict(
        {"homeassistant": {"url": "http://${OS_TEST_HOST}:8123", "token": "${OS_TEST_TOKEN}"}}
    )
    assert config.homeassistant.url == "http://10.0.0.5:8123"
    assert config.homeassistant.token == "from-env"


@pytest.mark.parametrize(
    ("env", "value", "expected"),
    [
        ({}, "${OS_TEST_VOICE:-lessac}", "lessac"),
        ({"OS_TEST_VOICE": "thorsten"}, "${OS_TEST_VOICE:-lessac}", "thorsten"),
        ({}, "${OS_TEST_VOICE:-}", None),  # "${X:-}" on its own means "no value"
        ({"OS_TEST_VOICE": ""}, "${OS_TEST_VOICE}", None),
        ({}, "voice-${OS_TEST_VOICE:-}", "voice-"),
        ({"OS_TEST_VOICE": "a", "OS_TEST_SIZE": "b"}, "${OS_TEST_VOICE}/${OS_TEST_SIZE}", "a/b"),
        ({}, "pa$$word-$HOME-${lower", "pa$$word-$HOME-${lower"),  # only ${NAME} is special
    ],
)
def test_environment_variable_expansion(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], value: str, expected: str | None
) -> None:
    monkeypatch.delenv("OS_TEST_VOICE", raising=False)
    for name, setting in env.items():
        monkeypatch.setenv(name, setting)
    assert build(tts={"voice": value}).tts.voice == expected


def test_environment_variables_in_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OS_TEST_KEY", "sk-local")
    monkeypatch.delenv("OS_TEST_WAKE", raising=False)
    config = build(
        wake={"names": ["${OS_TEST_WAKE:-okay_nabu}"]},
        agents=[{}, {**LLM, "api_key": "${OS_TEST_KEY}"}],
    )
    assert config.wake.names == ["okay_nabu"]
    assert config.agents[1].api_key == "sk-local"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            {"homeassistant": {"url": "http://ha:8123", "token": "${OS_TEST_MISSING}"}},
            "homeassistant.token: environment variable OS_TEST_MISSING is not set",
        ),
        (
            {**HA, "wake": {"names": ["alexa", "${OS_TEST_MISSING}"]}},
            "wake.names[1]: environment variable OS_TEST_MISSING is not set",
        ),
        (
            {**HA, "agents": [{**LLM, "api_key": "${OS_TEST_MISSING}"}]},
            "agents[0].api_key: environment variable OS_TEST_MISSING is not set",
        ),
    ],
)
def test_a_missing_environment_variable_is_an_error(
    monkeypatch: pytest.MonkeyPatch, data: dict[str, Any], message: str
) -> None:
    monkeypatch.delenv("OS_TEST_MISSING", raising=False)
    assert problems(data) == [message]


# ---------------------------------------------------------------------------
# Types


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"volume": 50}, "unknown option(s): volume"),
        ({"zeta": 1, "alpha": 2}, "unknown option(s): alpha, zeta"),
        ({"audio": {"input": {"chanels": 2}}}, "unknown option(s): audio.input.chanels"),
        ({"display": {"oled": {"brightness": 9}}}, "unknown option(s): display.oled.brightness"),
        (
            {"agents": [LLM, {"engine": "openai", "modle": "x"}]},
            "unknown option(s): agents[1].modle",
        ),
    ],
)
def test_unknown_options_are_rejected(data: dict[str, Any], message: str) -> None:
    assert problems({**HA, **data}) == [message]


@pytest.mark.parametrize(
    ("path", "value", "expected"),
    [
        ("display.oled.rotate", 180, 180),
        ("audio.input.channel", 1, 1),
        ("audio.input.channel", "mix", "mix"),
        ("vad.silence_seconds", 1, 1.0),
        ("tts.speed", 2, 2.0),
        ("wake.threshold", 0.6, 0.6),
        ("tts.voice", 3, "3"),
        ("audio.output.mixer_card", 1, "1"),
        ("volume_led.pin", None, None),
        ("display.night_start", None, None),
        ("wake.names", ["hey_jarvis", "alexa"], ["hey_jarvis", "alexa"]),
        ("wake.names", [], []),
    ],
)
def test_values_are_converted_to_the_option_type(path: str, value: Any, expected: Any) -> None:
    result = lookup(build(**nested(path, value)), path)
    assert result == expected
    assert type(result) is type(expected)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (
            "wake.engine",
            "snowboy",
            "wake.engine: must be one of 'microwakeword', 'openwakeword', "
            "'wyoming', 'none', got 'snowboy'",
        ),
        ("display.oled.rotate", 90, "display.oled.rotate: must be one of 0, 180, got 90"),
        ("display.oled.rotate", "180", "display.oled.rotate: must be one of 0, 180, got '180'"),
        ("display.oled.rotate", False, "display.oled.rotate: must be one of 0, 180, got False"),
        (
            "audio.input.channel",
            "left",
            "audio.input.channel: expected an integer or 'mix', got 'left'",
        ),
        (
            "audio.input.channel",
            True,
            "audio.input.channel: expected an integer or 'mix', got True",
        ),
        ("audio.input.channel", None, "audio.input.channel: a value is required"),
        ("pipeline.follow_up", "yes", "pipeline.follow_up: expected true/false, got 'yes'"),
        ("pipeline.follow_up", 1, "pipeline.follow_up: expected true/false, got 1"),
        ("audio.initial_volume", 50.5, "audio.initial_volume: expected an integer, got 50.5"),
        ("audio.initial_volume", True, "audio.initial_volume: expected an integer, got True"),
        ("vad.max_seconds", "long", "vad.max_seconds: expected a number, got 'long'"),
        ("wake.threshold", "high", "wake.threshold: expected a number, got 'high'"),
        ("volume_led.pin", "12", "volume_led.pin: expected an integer, got '12'"),
        ("name", None, "name: expected a string, got None"),
        ("name", True, "name: expected a string, got True"),
        ("wake.names", "alexa", "wake.names: expected a list, got 'alexa'"),
        ("agents", {"engine": "openai"}, "agents: expected a list, got {'engine': 'openai'}"),
        ("agents", ["openai"], "agents[0]: expected a mapping, got 'openai'"),
        ("audio", 5, "audio: expected a mapping, got 5"),
        ("audio.input", [], "audio.input: expected a mapping, got []"),
    ],
)
def test_values_of_the_wrong_type_are_rejected(path: str, value: Any, message: str) -> None:
    assert problems({**HA, **nested(path, value)}) == [message]


def test_agents_are_a_list_of_sections() -> None:
    config = build(agents=[{**LLM, "temperature": 0, "max_tokens": None}, {}])
    assert config.agents == [
        AgentConfig(
            engine="openai",
            url="http://10.0.0.2:11434/v1",
            model="llama3.2",
            temperature=0.0,
            max_tokens=None,
        ),
        AgentConfig(),
    ]


# ---------------------------------------------------------------------------
# Validation


@pytest.mark.parametrize(
    "data",
    [
        {"homeassistant": {"url": "http://ha.test:8123"}},
        {"homeassistant": {"token": "secret"}},
        {"homeassistant": {"url": "http://ha.test:8123", "token": "${OS_TEST_EMPTY:-}"}},
    ],
)
def test_home_assistant_mode_needs_a_url_and_a_token(data: dict[str, Any]) -> None:
    assert problems(data) == [HA_REQUIRED]


@pytest.mark.parametrize(
    "data",
    [
        LOCAL,
        {**LOCAL, "stt": {"uri": "unix:///run/whisper.sock"}},
        {
            **LOCAL,
            "stt": {"engine": "openai", "url": "https://stt.lan/v1"},
            "tts": {"engine": "openai", "url": "http://tts.lan:8000/v1"},
        },
        {**LOCAL, **HA, "agents": [{"agent_id": "conversation.ollama"}, LLM]},
    ],
)
def test_valid_local_pipelines(data: dict[str, Any]) -> None:
    assert config_from_dict(data).pipeline.mode == "local"


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (
            {"pipeline": {"mode": "local"}},
            [
                "stt.uri is required (e.g. tcp://192.168.1.10:10300)",
                "tts.uri is required (e.g. tcp://192.168.1.10:10300)",
                "agents[0] uses Home Assistant, so homeassistant.url and homeassistant.token "
                "are required",
            ],
        ),
        (
            {
                **LOCAL,
                "stt": {"engine": "openai"},
                "tts": {"engine": "openai"},
                "agents": [{"engine": "openai"}],
            },
            [
                "stt.url is required (e.g. http://192.168.1.10:8000/v1)",
                "tts.url is required (e.g. http://192.168.1.10:8000/v1)",
                "agents[0].url is required (e.g. http://192.168.1.10:8000/v1)",
                "agents[0].model is required",
            ],
        ),
        ({**LOCAL, "agents": []}, ["agents: at least one agent is required"]),
        (
            {**LOCAL, "agents": [LLM, {}]},
            [
                "agents[1] uses Home Assistant, so homeassistant.url and homeassistant.token "
                "are required"
            ],
        ),
        (
            {**LOCAL, "stt": {"uri": "http://10.0.0.2:10300"}},
            ["stt.uri must start with tcp:// or unix://, got 'http://10.0.0.2:10300'"],
        ),
        (
            {**LOCAL, "tts": {"uri": "10.0.0.2:10200"}},
            ["tts.uri must start with tcp:// or unix://, got '10.0.0.2:10200'"],
        ),
        (
            {**LOCAL, "stt": {"engine": "openai", "url": "tcp://10.0.0.2:8000"}},
            ["stt.url must start with http:// or https://, got 'tcp://10.0.0.2:8000'"],
        ),
        (
            {**LOCAL, "agents": [{**LLM, "url": "localhost:11434"}]},
            ["agents[0].url must start with http:// or https://, got 'localhost:11434'"],
        ),
        (
            {"homeassistant": {"url": "ha.local:8123", "token": "t"}},
            ["homeassistant.url must start with http:// or https://, got 'ha.local:8123'"],
        ),
        (
            {**HA, "wake": {"engine": "wyoming"}},
            ["wake.uri is required (e.g. tcp://192.168.1.10:10300)"],
        ),
        (
            {**HA, "wake": {"engine": "wyoming", "uri": "10.0.0.2:10400"}},
            ["wake.uri must start with tcp:// or unix://, got '10.0.0.2:10400'"],
        ),
    ],
)
def test_pipeline_requirements(data: dict[str, Any], expected: list[str]) -> None:
    assert problems(data) == expected


@pytest.mark.parametrize(
    ("sections", "message"),
    [
        ({"audio": {"initial_volume": 101}}, "audio.initial_volume must be 0-100"),
        ({"audio": {"volume_step": 0}}, "audio.volume_step must be 1-50"),
        ({"audio": {"input": {"channels": 0}}}, "audio.input.channels must be at least 1"),
        ({"audio": {"input": {"channel": 2}}}, "audio.input.channel must be 'mix' or 0-1"),
        ({"audio": {"input": {"samples_per_chunk": 100}}}, "audio.input.samples_per_chunk >= 160"),
        ({"audio": {"output": {"duck_volume": 101}}}, "audio.output.duck_volume must be 0-100"),
        ({"audio": {"output": {"sound_volume": 0}}}, "audio.output.sound_volume must be 0-1"),
        ({"wake": {"threshold": 1.0}}, "wake.threshold must be between 0 and 1"),
        ({"wake": {"model": ""}}, "wake.model is required"),
        ({"vad": {"silence_seconds": 0}}, "vad.silence_seconds must be positive"),
        ({"vad": {"silence_seconds": 2, "max_seconds": 2}}, "vad.max_seconds is too small"),
        (
            {"display": {"night_start": "25:00"}},
            "display.night_start must be a 24-hour time like 22:00, got '25:00'",
        ),
        (
            {"display": {"night_end": "7am"}},
            "display.night_end must be a 24-hour time like 22:00, got '7am'",
        ),
        ({"display": {"oled": {"contrast": 256}}}, "display.oled.contrast must be 0-255"),
        (
            {"display": {"oled": {"night_contrast": -1}}},
            "display.oled.night_contrast must be 0-255",
        ),
        ({"display": {"tm1637": {"brightness": 8}}}, "display.tm1637.brightness must be 0-7"),
        ({"status_leds": {"brightness": 0}}, "status_leds.brightness must be 0-1"),
        ({"status_leds": {"count": 0}}, "status_leds.count must be at least 1"),
        (
            {"status_leds": {"color_order": "RGW"}},
            "status_leds.color_order must be a permutation of RGB",
        ),
        ({"api": {"port": 65536}}, "api.port must be 1-65535"),
        ({"timers": {"snooze_minutes": 0}}, "timers.snooze_minutes must be at least 1"),
    ],
)
def test_out_of_range_values(sections: dict[str, Any], message: str) -> None:
    assert problems({**HA, **sections}) == [message]


def test_values_at_the_limits_are_accepted() -> None:
    config = build(
        audio={"initial_volume": 100, "volume_step": 50, "output": {"sound_volume": 1}},
        wake={"threshold": 0.99},
        display={"night_start": "0:00", "night_end": "23:59", "tm1637": {"brightness": 7}},
        status_leds={"color_order": "brg", "brightness": 1},
        api={"port": 65535},
        timers={"snooze_minutes": 1},
    )
    assert config.status_leds.color_order == "brg"


def test_every_problem_is_reported_at_once() -> None:
    with pytest.raises(ConfigError) as err:
        config_from_dict(
            {"pipeline": {"mode": "local"}, "api": {"port": 0}, "buttons": {"mute": 18}}
        )
    message = str(err.value)
    assert message.startswith("invalid configuration:\n  - ")
    assert "stt.uri is required" in message
    assert "api.port must be 1-65535" in message
    assert "buttons.mute: GPIO18 is already used by I2S audio" in message


# ---------------------------------------------------------------------------
# GPIO pins


def test_used_pins() -> None:
    assert used_pins(build()) == {
        17: "buttons.volume_up",
        27: "buttons.volume_down",
        22: "buttons.mute",
        5: "buttons.action",
        12: "volume_led.pin",
    }
    none = dict.fromkeys(("volume_up", "volume_down", "mute", "action"))
    assert used_pins(build(buttons=none, volume_led={"pin": None})) == {}
    tm1637 = used_pins(build(display={"type": "tm1637"}))
    assert (tm1637[23], tm1637[24]) == ("display.tm1637.clk_pin", "display.tm1637.dio_pin")


@pytest.mark.parametrize("pin", [18, 19, 20, 21])
def test_i2s_pins_are_reserved(pin: int) -> None:
    assert problems({**HA, "buttons": {"action": pin}}) == [
        f"buttons.action: GPIO{pin} is already used by I2S audio"
    ]


def test_the_amplifier_shutdown_pin_is_reserved() -> None:
    assert problems({**HA, "volume_led": {"pin": 16}}) == [
        "volume_led.pin: GPIO16 is already used by the I2S amplifier driver (SD_MODE)"
    ]


@pytest.mark.parametrize("pin", [2, 3])
def test_i2c_pins_are_reserved_while_the_oled_is_fitted(pin: int) -> None:
    assert problems({**HA, "buttons": {"mute": pin}}) == [
        f"buttons.mute: GPIO{pin} is already used by the OLED display (I2C)"
    ]
    for display in ("none", "tm1637"):
        assert build(buttons={"mute": pin}, display={"type": display}).buttons.mute == pin


@pytest.mark.parametrize("pin", [7, 8, 9, 10, 11])
def test_spi0_pins_are_reserved_while_ws2812_leds_are_fitted(pin: int) -> None:
    assert problems({**HA, "buttons": {"volume_up": pin}}) == [
        f"buttons.volume_up: GPIO{pin} is already used by the status LEDs (SPI0)"
    ]
    assert build(buttons={"volume_up": pin}, status_leds={"type": "none"}).buttons.volume_up == pin


def test_ws2812_leds_cannot_use_spi1() -> None:
    assert problems({**HA, "status_leds": {"spi_bus": 1}}) == [
        "status_leds.spi_bus must be 0: SPI1 uses GPIO19-21, which the I2S audio needs"
    ]
    assert build(status_leds={"type": "none", "spi_bus": 1}).status_leds.spi_bus == 1


@pytest.mark.parametrize(
    ("sections", "message"),
    [
        (
            {"buttons": {"mute": 17}},
            "GPIO pins used twice: GPIO17 (buttons.volume_up and buttons.mute)",
        ),
        (
            {"buttons": {"mute": 17, "action": 27}},
            "GPIO pins used twice: GPIO17 (buttons.volume_up and buttons.mute); "
            "GPIO27 (buttons.volume_down and buttons.action)",
        ),
        (
            {"volume_led": {"pin": 5}},
            "GPIO pins used twice: GPIO5 (buttons.action and volume_led.pin)",
        ),
        (
            {"display": {"type": "tm1637", "tm1637": {"clk_pin": 17}}},
            "GPIO pins used twice: GPIO17 (buttons.volume_up and display.tm1637.clk_pin)",
        ),
        (
            {"display": {"type": "tm1637", "tm1637": {"dio_pin": 19}}},
            "display.tm1637.dio_pin: GPIO19 is already used by I2S audio",
        ),
    ],
)
def test_pin_conflicts(sections: dict[str, Any], message: str) -> None:
    assert problems({**HA, **sections}) == [message]


def test_tm1637_pins_are_free_while_the_display_is_an_oled() -> None:
    assert build(display={"tm1637": {"clk_pin": 17}}).display.tm1637.clk_pin == 17


@pytest.mark.parametrize("pin", [-1, 28, 40])
def test_pins_must_exist(pin: int) -> None:
    assert problems({**HA, "buttons": {"action": pin}}) == [
        f"buttons.action: GPIO{pin} does not exist on the 40-pin header"
    ]


# ---------------------------------------------------------------------------
# Output


def test_config_to_dict_hides_secrets() -> None:
    config = build(
        api={"token": "api-secret"},
        stt={"api_key": "stt-secret"},
        tts={"api_key": "tts-secret"},
        agents=[{**LLM, "api_key": "llm-secret"}],
    )
    data = config_to_dict(config)
    assert data["homeassistant"] == {
        "url": "http://ha.test:8123",
        "token": "***",
        "pipeline": None,
        "verify_ssl": True,
        "timeout": 30.0,
    }
    assert data["api"]["token"] == "***"
    assert (data["stt"]["api_key"], data["tts"]["api_key"]) == ("***", "***")
    assert data["agents"][0]["api_key"] == "***"
    assert data["agents"][0]["model"] == "llama3.2"
    assert "secret" not in json.dumps(data)


def test_unset_secrets_stay_empty(config: Config) -> None:
    data = config_to_dict(config)
    assert data["homeassistant"]["token"] == "***"
    assert data["api"]["token"] is None
    assert data["agents"][0]["api_key"] is None


def test_config_to_dict_round_trip(config: Config) -> None:
    data = config_to_dict(config, redact=False)
    assert data["homeassistant"]["token"] == "secret"
    assert json.loads(json.dumps(data)) == data
    assert config_from_dict(data) == config


# ---------------------------------------------------------------------------
# Files


def test_load_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OS_TEST_TOKEN", "from-env")
    path = tmp_path / "config.yaml"
    path.write_text(
        "name: Kitchen\n"
        "homeassistant:\n"
        "  url: http://homeassistant.local:8123\n"
        "  token: ${OS_TEST_TOKEN}\n"
        "audio:\n"
        "  volume_step: 10\n"
        "  input:\n"
        "    channel: 1\n"
        "display:\n"
        "  oled:\n"
        "    address: 0x3D\n"
        "    rotate: 180\n"
        "timers:            # nothing set: the defaults\n"
        "agents:\n"
        "  - engine: homeassistant\n"
        "    agent_id: conversation.ollama\n"
        "  - engine: openai\n"
        "    url: http://192.168.1.10:11434/v1\n"
        "    model: llama3.2\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.name == "Kitchen"
    assert config.homeassistant.token == "from-env"
    assert (config.audio.volume_step, config.audio.input.channel) == (10, 1)
    assert (config.display.oled.address, config.display.oled.rotate) == (0x3D, 180)
    assert config.timers == TimersConfig()
    assert [agent.engine for agent in config.agents] == ["homeassistant", "openai"]
    assert config.agents[0].agent_id == "conversation.ollama"
    assert load_config(str(path)) == config


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (None, "configuration file not found"),
        ("audio: [unclosed\n", "invalid YAML"),
        ("- name: Kitchen\n", "the top level must be a mapping"),
        ("", HA_REQUIRED),
        (
            "homeassistant:\n  url: http://ha:8123\n  tokn: x\n",
            "unknown option(s): homeassistant.tokn",
        ),
    ],
)
def test_load_config_errors(tmp_path: Path, content: str | None, message: str) -> None:
    path = tmp_path / "config.yaml"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError, match=re.escape(message)):
        load_config(path)


def test_the_example_config_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HA_TOKEN", "example-token")
    with example_config() as path:
        config = load_config(path)
    assert config.homeassistant.token == "example-token"
    assert config.pipeline.mode == "homeassistant"


def test_the_example_config_shows_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """It says every option shows its default unless marked "example"."""
    monkeypatch.setenv("HA_TOKEN", "example-token")
    with example_config() as path:
        config = load_config(path)
    assert config == Config(
        homeassistant=HomeAssistantConfig("http://homeassistant.local:8123", "example-token"),
        stt=SttConfig(uri="tcp://192.168.1.10:10300"),
        tts=TtsConfig(uri="tcp://192.168.1.10:10200"),
    )


def test_the_example_config_reads_the_token_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HA_TOKEN", raising=False)
    with (
        example_config() as path,
        pytest.raises(ConfigError, match=re.escape("homeassistant.token: environment variable")),
    ):
        load_config(path)
