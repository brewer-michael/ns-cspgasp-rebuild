# ESP32-S3 brain (ESPHome)

[`open-speaker.yaml`](open-speaker.yaml) runs the speaker on an ESP32-S3 with
[ESPHome](https://esphome.io). The ESP32-S3 listens for the wake word itself and
Home Assistant's Assist pipeline does the rest: speech-to-text, the assistant and
text-to-speech. Point that pipeline at your own servers (Whisper, Piper, Ollama)
or at a cloud service.

The rest of the hardware is the same as the Raspberry Pi build. For the Pi's
software, see [`../firmware`](../firmware).

## What you need

- An **ESP32-S3-DevKitC-1 with 8 MB flash and 8 MB PSRAM** (N8R8), wired as in
  [gpio_pinout.md](../hardware/schematics/gpio_pinout.md#esp32-s3). It sits on the
  printed `esp32_cradle` in the enclosure.
- **Home Assistant** with the ESPHome integration and an Assist pipeline
  ([HOME_ASSISTANT.md](../docs/HOME_ASSISTANT.md#esp32-s3-speaker)).
- **ESPHome 2026.9 or newer**: the ESPHome Device Builder in Home Assistant, or
  `pip install esphome` on a computer.

## Install

1. In the ESPHome Device Builder, create a new device. Replace its YAML with the
   following, keeping the API encryption key it generated:

   ```yaml
   substitutions:
     name: open-speaker
     friendly_name: Open Speaker
     temperature_entity: weather.forecast_home

   packages:
     open_speaker: github://brewer-michael/ns-cspgasp-rebuild/esphome/open-speaker.yaml@v2

   wifi:
     ssid: !secret wifi_ssid
     password: !secret wifi_password

   api:
     encryption:
       key: "..."
   ```

2. Unplug the speaker's power supply, then connect either of the DevKitC's USB-C
   ports to the computer. **Never power the DevKitC from its USB port and the
   5 V wire at the same time.**
3. Choose **Install**, then **Plug into this computer**. Later updates go over
   Wi-Fi.
4. Home Assistant discovers the speaker; add it under **Settings → Devices &
   services**. On the device page, pick the Assist pipeline it should use.

For several speakers, give each its own `name` and `friendly_name`.

Without the Device Builder, from a copy of this repository:

```sh
esphome run esphome/open-speaker.yaml
```

With no Wi-Fi details the speaker opens a hotspot named after it. Join it to
enter your Wi-Fi, or use Improv over USB at [web.esphome.io](https://web.esphome.io).

## Settings

Set these under `substitutions:` in your own YAML.

| Setting | Default | |
|---|---|---|
| `wake_word` | `okay_nabu` | Also `hey_jarvis`, `hey_mycroft` or `alexa` |
| `temperature_entity` | `weather.forecast_home` | Any weather or temperature sensor entity |
| `temperature_attribute` | `temperature` | Set it to `""` for a sensor entity |
| `temperature_unit` | `°` | For example `°F` |
| `clock_24h` | `false` | `true` for a 24-hour clock |
| `night_start_hour`, `night_end_hour` | `22`, `7` | The display and the light dim between these hours |
| `mic_gain` | `4` | Raise it if the wake word needs you to speak up, 1 to 64 |
| `*_pin` | see the file | Only if your wiring differs |

## In Home Assistant

| Entity or action | |
|---|---|
| Media player | Volume, announcements and music |
| Mute microphone | The back button toggles it too |
| Alarm, Alarm time, Alarm days | The alarm clock. It rings from the speaker's own clock, so it works while Home Assistant is down. |
| Stop ringing | Stops an alarm or timer |
| Wake sound | The chime when it starts listening |
| `esphome.<name>_ring_alarm`, `esphome.<name>_stop_ringing` | Actions for automations |

Timers work by voice ("set a timer for ten minutes"). Home Assistant keeps track of
them and the speaker counts down on the display and rings.

## Differences from the Raspberry Pi build

- It needs Home Assistant. It can't talk to Wyoming or OpenAI-compatible servers
  directly, so connect those to Home Assistant's pipeline instead.
- Timers need Home Assistant to be running. Alarms don't.
- You can't set alarms by voice yet. Set them in Home Assistant, or write an
  automation that sets **Alarm time**.
- It listens with the left microphone only.
- There's no HTTP API. Automations use the entities and actions above.

## For developers

- Validate: `esphome config esphome/open-speaker.yaml`.
- Build from your working copy instead of GitHub:
  `esphome -s sounds sounds compile esphome/open-speaker.yaml`.
- The sounds in [`sounds/`](sounds) are the Linux firmware's built-in sounds.
  After changing one there, run `python3 scripts/make_esphome_sounds.py`.
- CI builds this file on every push.
