"""The command line, including the audio helpers run against fake players and recorders."""

from __future__ import annotations

import http.server
import json
import shlex
import struct
import subprocess
import sys
import threading
import wave
from collections.abc import Iterator
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import tone

from open_speaker import __version__, cli
from open_speaker.audio.pcm import wav_bytes
from open_speaker.audio.sounds import load_sound
from open_speaker.config import config_to_dict, load_config
from open_speaker.const import DEFAULT_CONFIG_PATH

FIRMWARE = Path(__file__).resolve().parents[1]
MINIMAL = "homeassistant:\n  url: http://homeassistant.local:8123\n  token: abc123\n"
ANSWER = "Paris is the capital of France."
SPEECH = tone(0.05)  # what the fake text-to-speech server says


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    """Run the command line; returns (exit code, stdout, stderr)."""
    try:
        cli.main(list(argv))
    except SystemExit as stop:
        code = 0 if stop.code is None else stop.code
    else:
        code = 0
    out, err = capsys.readouterr()
    return code, out, err


def write_config(tmp_path: Path, data: dict[str, Any] | str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(data if isinstance(data, str) else yaml.safe_dump(data))
    return path


class _Handler(http.server.BaseHTTPRequestHandler):
    server: FakeOpenAiServer

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.requests.append((self.path, json.loads(body)))
        if self.path == "/v1/chat/completions":
            reply = {"choices": [{"message": {"role": "assistant", "content": ANSWER}}]}
            self._send("application/json", json.dumps(reply).encode())
        elif self.path == "/v1/audio/speech":
            self._send("audio/wav", wav_bytes(SPEECH, 16000))
        else:
            self.send_error(404)

    def _send(self, content_type: str, payload: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        pass


class FakeOpenAiServer(http.server.ThreadingHTTPServer):
    """An OpenAI-compatible language model and text-to-speech server on 127.0.0.1."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.requests: list[tuple[str, Any]] = []

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/v1"

    def body(self, path: str) -> Any:
        return next(body for requested, body in self.requests if requested == path)


@pytest.fixture
def openai_server() -> Iterator[FakeOpenAiServer]:
    server = FakeOpenAiServer()
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def local_config(tmp_path: Path, url: str, player: str = "true") -> Path:
    return write_config(
        tmp_path,
        {
            "pipeline": {"mode": "local"},
            "stt": {"engine": "openai", "url": url},
            "tts": {"engine": "openai", "url": url, "voice": "nova"},
            "agents": [{"engine": "openai", "url": url, "model": "tiny-llm"}],
            "audio": {"output": {"command": player, "volume_control": None}},
        },
    )


def tee(path: Path) -> str:
    """A player command that writes the raw audio to ``path``."""
    return f"tee {shlex.quote(str(path))}"


# ---------------------------------------------------------------------------
# Version and configuration


def test_version(capsys) -> None:
    code, out, _ = run(capsys, "--version")
    assert (code, out.strip()) == (0, f"open-speaker {__version__}")


def test_the_package_runs_as_a_module() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "open_speaker", "--version"],
        cwd=FIRMWARE,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert (result.returncode, result.stdout.strip()) == (0, f"open-speaker {__version__}")


def test_example_config_prints_the_packaged_example(capsys) -> None:
    code, out, err = run(capsys, "example-config")
    example = resources.files("open_speaker").joinpath("data/config.example.yaml").read_text()
    assert (code, out, err) == (0, example, "")
    assert out.startswith("# Open Speaker configuration")


def test_example_config_passes_check_config(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("HA_TOKEN", "a-long-lived-token")
    _, example, _ = run(capsys, "example-config")
    path = write_config(tmp_path, example)
    code, out, err = run(capsys, "-c", str(path), "check-config")
    assert code == 0
    effective = yaml.safe_load(out)
    assert effective["pipeline"]["mode"] == "homeassistant"
    assert effective["homeassistant"]["token"] == "***"
    assert "a-long-lived-token" not in out
    assert err.strip() == f"{path}: OK"


def test_check_config_prints_the_effective_configuration(tmp_path, capsys) -> None:
    path = write_config(tmp_path, MINIMAL + "audio:\n  initial_volume: 30\n")
    code, out, err = run(capsys, "--config", str(path), "check-config")
    assert code == 0
    effective = yaml.safe_load(out)
    assert effective == config_to_dict(load_config(path))
    assert effective["homeassistant"] == {
        "url": "http://homeassistant.local:8123",
        "token": "***",
        "pipeline": None,
        "verify_ssl": True,
        "timeout": 30.0,
    }
    assert effective["audio"]["initial_volume"] == 30
    assert effective["api"]["port"] == 10800  # defaults are filled in
    assert "abc123" not in out
    assert err.strip() == f"{path}: OK"


def test_check_config_reads_secrets_from_the_environment(tmp_path, capsys, monkeypatch) -> None:
    path = write_config(
        tmp_path, "homeassistant:\n  url: http://homeassistant.local:8123\n  token: ${HA_TOKEN}\n"
    )
    monkeypatch.delenv("HA_TOKEN", raising=False)
    code, out, err = run(capsys, "-c", str(path), "check-config")
    assert (code, out) == (2, "")
    assert "environment variable HA_TOKEN is not set" in err
    monkeypatch.setenv("HA_TOKEN", "from-the-environment")
    code, out, _ = run(capsys, "-c", str(path), "check-config")
    assert code == 0
    assert yaml.safe_load(out)["homeassistant"]["token"] == "***"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("homeassistant: [unclosed", "invalid YAML"),
        ("- just\n- a list\n", "the top level must be a mapping"),
        (MINIMAL + "wake:\n  modle: hey_jarvis\n", "unknown option(s): wake.modle"),
        (MINIMAL + "audio:\n  initial_volume: loud\n", "audio.initial_volume: expected an integer"),
        (MINIMAL + "audio:\n  initial_volume: 150\n", "audio.initial_volume must be 0-100"),
        (MINIMAL + "buttons:\n  action: 18\n", "buttons.action: GPIO18 is already used by I2S"),
        ("pipeline:\n  mode: local\n", "stt.uri is required"),
        ("pipeline:\n  mode: homeassistant\n", "homeassistant.url and homeassistant.token"),
    ],
)
def test_check_config_rejects_invalid_files(tmp_path, capsys, text, message) -> None:
    path = write_config(tmp_path, text)
    code, out, err = run(capsys, "-c", str(path), "check-config")
    assert (code, out) == (2, "")
    assert err.startswith("Configuration error: ")
    assert message in err


def test_check_config_of_a_missing_file(tmp_path, capsys) -> None:
    missing = tmp_path / "missing.yaml"
    code, out, err = run(capsys, "-c", str(missing), "check-config")
    assert (code, out) == (2, "")
    assert err.strip() == f"Configuration error: configuration file not found: {missing}"


def test_default_config_path() -> None:
    assert cli.build_parser().parse_args(["check-config"]).config == DEFAULT_CONFIG_PATH


def test_run_is_the_default_command(monkeypatch) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(cli, "cmd_run", calls.append)
    cli.main(["-c", "speaker.yaml", "--debug"])
    assert [(args.config, args.debug) for args in calls] == [("speaker.yaml", True)]


def test_run_refuses_a_bad_configuration(tmp_path, capsys) -> None:
    code, _, err = run(capsys, "-c", str(tmp_path / "missing.yaml"), "run")
    assert code == 2
    assert "configuration file not found" in err


def test_unknown_command(capsys) -> None:
    code, _, err = run(capsys, "frobnicate")
    assert code == 2
    assert "invalid choice: 'frobnicate'" in err


# ---------------------------------------------------------------------------
# Speech helpers, against a fake OpenAI-compatible server


def test_ask_reports_requests_the_speaker_handles_itself(tmp_path, capsys) -> None:
    path = write_config(tmp_path, MINIMAL)
    code, out, _ = run(capsys, "-c", str(path), "ask", "set", "a", "timer", "for", "5", "minutes")
    assert code == 0
    assert out.strip() == (
        "(handled on the speaker by the running service: StartTimer(seconds=300, name=None))"
    )


def test_ask_prints_the_reply(tmp_path, capsys, openai_server) -> None:
    path = local_config(tmp_path, openai_server.url)
    code, out, _ = run(capsys, "-c", str(path), "ask", "-q", "what's the capital", "of France")
    assert (code, out.strip()) == (0, ANSWER)
    chat = openai_server.body("/v1/chat/completions")
    assert chat["model"] == "tiny-llm"
    assert chat["messages"][-1] == {"role": "user", "content": "what's the capital of France"}


def test_ask_speaks_the_reply(tmp_path, capsys, openai_server) -> None:
    played = tmp_path / "played.raw"
    path = local_config(tmp_path, openai_server.url, player=tee(played))
    code, out, _ = run(capsys, "-c", str(path), "ask", "what's the capital of France")
    assert (code, out.strip()) == (0, ANSWER)
    assert openai_server.body("/v1/audio/speech")["input"] == ANSWER
    assert played.read_bytes() == SPEECH


def test_say_speaks_through_the_configured_player(tmp_path, capsys, openai_server) -> None:
    played = tmp_path / "played.raw"
    path = local_config(tmp_path, openai_server.url, player=tee(played))
    code, out, _ = run(capsys, "-c", str(path), "say", "Dinner", "is", "ready")
    assert (code, out) == (0, "")
    assert openai_server.body("/v1/audio/speech") == {
        "model": "tts-1",
        "input": "Dinner is ready",
        "voice": "nova",
        "response_format": "wav",
    }
    assert [path for path, _ in openai_server.requests] == ["/v1/audio/speech"]
    assert played.read_bytes() == SPEECH


# ---------------------------------------------------------------------------
# Audio tests, with fake player and recorder commands


def test_test_speaker_plays_the_builtin_sounds(tmp_path, capsys) -> None:
    played = tmp_path / "played.raw"
    player = f"sh -c {shlex.quote(f'cat >> {shlex.quote(str(played))}')}"
    path = write_config(
        tmp_path, {**yaml.safe_load(MINIMAL), "audio": {"output": {"command": player}}}
    )
    code, out, _ = run(capsys, "-c", str(path), "test-speaker")
    assert code == 0
    assert out.splitlines() == [
        "Playing wake sound...",
        "Playing done sound...",
        "Playing timer sound...",
    ]
    sounds = [load_sound(f"builtin:{name}") for name in ("wake", "done", "timer")]
    assert played.read_bytes() == b"".join(sound.pcm for sound in sounds if sound)


RECORDER = """\
import struct, sys, time
frame = struct.pack("<2h", {amplitude}, {amplitude})
while True:
    sys.stdout.buffer.write(frame * 512)
    sys.stdout.buffer.flush()
    time.sleep(0.005)
"""


@pytest.mark.parametrize(
    ("amplitude", "level", "quiet"), [(8000, "-12.2", False), (0, "-inf", True)]
)
def test_test_mic_shows_the_level_and_saves_a_recording(
    tmp_path, capsys, amplitude, level, quiet
) -> None:
    script = tmp_path / "recorder.py"
    script.write_text(RECORDER.format(amplitude=amplitude))
    recorder = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"
    path = write_config(
        tmp_path, {**yaml.safe_load(MINIMAL), "audio": {"input": {"command": recorder}}}
    )
    saved = tmp_path / "recording.wav"
    code, out, _ = run(
        capsys, "-c", str(path), "test-mic", "--seconds", "0.2", "--save", str(saved)
    )
    assert code == 0
    assert out.startswith("Recording 0 s from 'mics'; speak now...")
    assert f"Average level {level} dBFS." in out
    assert ("very quiet" in out) is quiet
    assert out.rstrip().endswith(f"Saved {saved}")
    with wave.open(str(saved)) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
        frames = wav.readframes(wav.getnframes())
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    assert len(samples) >= 512
    assert set(samples) == {amplitude}
