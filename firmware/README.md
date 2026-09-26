# open-speaker

The software for [Open Speaker](../README.md): a voice assistant and alarm clock
for a Raspberry Pi Zero 2 W, for Home Assistant or your own speech and language
model servers.

It runs as one asyncio process: microphone capture, the wake word, the voice
pipeline, timers and alarms, the display, LEDs, buttons and an HTTP API.

## Install

On the speaker, use the [installer](../scripts/install.sh). It also sets up the
sound card, the configuration and the systemd service. To install the package
alone:

```sh
python3 -m venv --system-site-packages venv
venv/bin/pip install ".[pi]"        # on a Raspberry Pi
venv/bin/pip install ".[dev]"       # on a PC, for development
```

Python 3.11 or newer. Extras: `pi` (microWakeWord, microVAD, GPIO, I2C, display),
`openwakeword`, `dev` (pytest, ruff).

## Commands

```
open-speaker [--config FILE] [--debug] COMMAND

  run              run the speaker (what the service does)
  check-config     validate the configuration and print it with defaults filled in
  example-config   print a commented example configuration
  doctor           check audio devices, microphones, display, LEDs, GPIO and servers
  test-speaker     play the built-in sounds [--say "text" to try text-to-speech too]
  test-mic         show microphone levels [--seconds N] [--save file.wav]
  say TEXT         speak TEXT through the voice pipeline
  ask TEXT         send a typed request to the assistant and play the answer
```

The configuration file is `/etc/open-speaker/config.yaml`. Every option is
explained in [`open_speaker/data/config.example.yaml`](open_speaker/data/config.example.yaml).
Values like `${HA_TOKEN}` come from the environment. The service gets them from
`/etc/open-speaker/secrets.env`, and the commands read the `secrets.env` next to
the configuration file themselves.

## Code map

| Module | |
|---|---|
| `app.py` | `Speaker`: state machine that ties everything together |
| `pipeline/` | Home Assistant Assist pipeline over WebSocket, or the local pipeline (STT, agents, TTS) |
| `wake/`, `vad.py` | microWakeWord / openWakeWord on the device, or a Wyoming wake word server; end-of-speech detection |
| `stt/`, `tts/`, `agents/` | Wyoming and OpenAI-compatible clients; Home Assistant and OpenAI-compatible (Ollama, llama.cpp, ...) conversation agents |
| `homeassistant.py` | Home Assistant REST and WebSocket client |
| `intents.py`, `timers.py` | Commands handled on the speaker; timers and alarms that survive restarts |
| `audio/` | `arecord`/`aplay` capture and playback, volume and ducking, built-in sounds |
| `hardware/`, `ui.py` | Buttons (gpiozero), OLED and TM1637 displays, WS2812B over SPI, the clock face |
| `api.py` | HTTP API for Home Assistant automations |
| `config.py`, `factory.py`, `cli.py`, `doctor.py` | Configuration, wiring up, command line, self-test |

## Development

```sh
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```

The tests use fake audio devices, fake GPIO pins and fake Home Assistant and
Wyoming servers, so they run on an ordinary PC; no Raspberry Pi needed.
