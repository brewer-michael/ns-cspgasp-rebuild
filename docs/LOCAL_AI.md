# Speech and AI models on your network

A Raspberry Pi Zero 2 W has four small Cortex-A53 cores and 512 MB of RAM. That is
plenty for a speaker, but not for speech recognition: even Whisper's smallest
model would take several seconds per command. So the work is split:

| On the speaker | On another machine on your network |
|---|---|
| Wake word (microWakeWord, a few percent of one core) | Speech-to-text |
| Recording, end-of-speech detection, playback | The conversation agent / language model |
| Timers, alarms, volume, stop, snooze | Text-to-speech |
| Display, LEDs, buttons | |

The "other machine" can be whatever already runs all the time: the Home
Assistant box, a mini PC, a NAS with Docker, or a desktop with a GPU.
[`server/docker-compose.yml`](../server/docker-compose.yml) starts everything
below with one command.

## Choosing models

**Speech-to-text**

| Server | Good for |
|---|---|
| [Speech-to-Phrase](https://github.com/OHF-Voice/speech-to-phrase) (Home Assistant add-on) | The lightest option; fast even on a Raspberry Pi 4. It only understands commands built from your Home Assistant devices and areas, so no open questions. |
| [faster-whisper](https://github.com/rhasspy/wyoming-faster-whisper) `tiny-int8` / `base-int8` | Any sentence, on a CPU. `base-int8` is the compose file's default. |
| faster-whisper `small-int8` or larger | Better accuracy; wants a fast CPU or a GPU |
| Any OpenAI-compatible `/v1/audio/transcriptions` server ([speaches](https://github.com/speaches-ai/speaches), LocalAI, vLLM) | If you already run one |

**Conversation agent / language model**

- Home Assistant's built-in agent: device control only, instant.
- [Ollama](https://ollama.com) with a small model that supports tool calling, such
  as `llama3.2` (3B) or `qwen2.5:7b`. On a CPU, expect a few seconds per answer;
  a GPU makes it feel instant.
- Anything with an OpenAI-compatible `/v1/chat/completions` API: llama.cpp's
  `llama-server`, vLLM, LocalAI, LM Studio.

**Text-to-speech**

- [Piper](https://github.com/rhasspy/wyoming-piper): fast on a CPU, many voices.
- Any OpenAI-compatible `/v1/audio/speech` server, e.g. Kokoro through speaches
  or Kokoro-FastAPI: more natural, heavier.

## Option A: through Home Assistant (default)

Add the servers to Home Assistant and build an Assist pipeline from them; see
[HOME_ASSISTANT.md](HOME_ASSISTANT.md#2-an-assist-pipeline-on-your-own-network).
The speaker needs only:

```yaml
pipeline:
  mode: homeassistant
homeassistant:
  url: http://homeassistant.local:8123
  token: ${HA_TOKEN}
```

## Option B: the speaker calls the servers itself

Useful without Home Assistant, or to mix engines Home Assistant doesn't offer. The
agents are tried in order: here Home Assistant controls the devices, and anything
it doesn't understand goes to the language model.

```yaml
pipeline:
  mode: local

stt:
  engine: wyoming
  uri: tcp://192.168.1.10:10300          # faster-whisper or Speech-to-Phrase

agents:
  - engine: homeassistant                # optional; needs the homeassistant section
  - engine: openai
    url: http://192.168.1.10:11434/v1    # Ollama
    model: llama3.2

tts:
  engine: wyoming
  uri: tcp://192.168.1.10:10200          # Piper
  voice: en_US-lessac-medium

vad:
  engine: energy        # detects the end of your sentence; microvad is more robust
  silence_seconds: 0.8
```

OpenAI-compatible servers instead of Wyoming:

```yaml
stt:
  engine: openai
  url: http://192.168.1.10:8000/v1
  model: Systran/faster-distil-whisper-small.en
tts:
  engine: openai
  url: http://192.168.1.10:8000/v1
  model: speaches-ai/Kokoro-82M-v1.0-ONNX
  voice: af_heart
```

Set `api_key:` on any of them if your server wants one (e.g. `${OPENAI_API_KEY}`
from `/etc/open-speaker/secrets.env`).

## Wake word

microWakeWord runs on the speaker by default (`okay_nabu`, `hey_jarvis`,
`hey_mycroft`, `alexa`, or your own model file). openWakeWord also runs on the
speaker but needs several times the CPU. Or run it on the server:

```yaml
wake:
  engine: wyoming
  uri: tcp://192.168.1.10:10400      # docker compose --profile wakeword up -d
  names: [ok_nabu]
```

This streams the microphone to the server all the time, so the on-device default
is usually better.

## Making it quick

- The installer turns off Wi-Fi power saving. It adds noticeable delay to every
  request.
- With Wyoming, your voice streams to the server while you talk; OpenAI-style
  servers receive it in one piece after you stop.
- Keep models loaded: Ollama unloads a model after 5 minutes by default
  (`OLLAMA_KEEP_ALIVE=24h` keeps it in memory).
- Timers, alarms, stop and volume never leave the speaker, so they answer at once.

Check everything with `sudo open-speaker doctor`: it tries each configured server
and reports what works.
