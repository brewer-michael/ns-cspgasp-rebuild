# Open Speaker

**An open-source rebuild of the Insignia NS-CSPGASP smart speaker: a voice
assistant and alarm clock for Home Assistant, with speech recognition and AI models
on your own network. Its brain is an ESP32-S3 or a Raspberry Pi Zero 2 W.**

![Open Speaker, light and dark](docs/images/enclosure.png)

Google stopped supporting the NS-CSPGASP's Assistant board, and its hardware is
locked down. This project keeps only the two speaker drivers and replaces
everything else with parts you can buy anywhere, in a 3D-printed enclosure on the
original's footprint.

- **Voice control through Home Assistant**: "Okay Nabu, turn off the kitchen
  lights".
- **Your models, on your network**: Whisper or Speech-to-Phrase for speech
  recognition, Ollama, llama.cpp or any OpenAI-compatible server for the
  conversation, Piper or Kokoro for the voice. Nothing leaves your home unless
  you choose a cloud service.
- **Light on the speaker**: only the wake word (microWakeWord) runs on the speaker.
  Speech recognition runs elsewhere.
- **A clock first**: the display always shows the time and temperature, like the
  original, and the alarm rings even when the network is down.
- **Stereo**, two MAX98357A amplifiers into the original drivers, in a tuned
  bass chamber.
- **Physical buttons** for volume, talk/stop/snooze and microphone mute. Status
  light in the waist.

![The clock face: time, AL/PM, and the temperature slot showing the temperature, the volume, a timer or "mic off"](docs/images/display.png)

## How it works

```
 Open Speaker                                      your network
 ┌──────────────────────────────┐
 │ 2 × INMP441 mics ─► wake word │   voice    ┌──────────────────────────────┐
 │ (microWakeWord)               │ ─────────► │ Home Assistant Assist pipeline│
 │                               │            │  (Pi: or your own servers):   │
 │ clock, alarm, volume,         │   reply    │  speech-to-text  (Whisper)    │
 │ mute: on the speaker          │ ◄───────── │  language model  (Ollama)     │
 │                               │            │  text-to-speech  (Piper)      │
 │ 2 × MAX98357A ─► 2 drivers    │            └──────────────────────────────┘
 │ OLED clock, LEDs, buttons     │ ◄── Home Assistant automations
 └──────────────────────────────┘
```

## Two brains

Everything except the brain is the same: drivers, amplifiers, microphones, display,
LEDs, buttons, enclosure and wiring. Pick one:

| | ESP32-S3 (default) | Raspberry Pi Zero 2 W |
|---|---|---|
| Board | ESP32-S3-DevKitC-1-N8R8, $15 | Pi Zero 2 WH and a microSD card, about $27 |
| Software | ESPHome: [`esphome/`](esphome/) | The `open-speaker` Linux service: [`firmware/`](firmware/) |
| Needs Home Assistant | Yes | No: it can also talk to your speech and AI servers directly |
| Timers and alarms | Timers by voice through Home Assistant; the alarm clock rings from the speaker's clock | Handled on the speaker, by voice, even when the network is down |
| Automations | ESPHome entities and actions | An HTTP API |
| Availability | Easy to buy | Often out of stock in 2026 |

The ESP32-S3 is the default because you can buy it everywhere and it is the
simplest to run. The Pi does more on its own.

## Hardware

| | |
|---|---|
| Brain | ESP32-S3-DevKitC-1 or Raspberry Pi Zero 2 W |
| Audio out | 2 × MAX98357A I2S class-D amplifiers, 3 W each, into the original 4 Ω drivers |
| Audio in | 2 × INMP441 I2S MEMS microphones |
| Display | 1.3" 128 × 64 OLED (on the Pi also a 2.42" OLED or a TM1637 7-segment display) |
| Controls | 4 tactile buttons, 3 WS2812B status LEDs |
| Power | 5 V 3 A over USB-C |
| Enclosure | 100 × 100 × 160 mm, PETG, no supports; ported bass chamber |

About $75 in parts per speaker with the ESP32-S3 ($87 with the Pi), or about $215
for the first one, because many parts come in packs: see the
[bill of materials](docs/BOM.md), with a link for every part. To shop, open
[docs/shopping-list.html](docs/shopping-list.html) in a browser.

## Getting started

1. **Build**: [docs/ASSEMBLY_GUIDE.md](docs/ASSEMBLY_GUIDE.md): teardown, wiring,
   testing on the desk, enclosure.
2. **Install**:
   - ESP32-S3: flash it with ESPHome, see [esphome/README.md](esphome/README.md).
   - Pi: on Raspberry Pi OS Lite (64-bit):

     ```sh
     git clone -b v2 https://github.com/brewer-michael/ns-cspgasp-rebuild.git
     sudo ns-cspgasp-rebuild/scripts/install.sh
     ```

3. **Connect**: [Home Assistant](docs/HOME_ASSISTANT.md). On the Pi, you can also
   use [your own speech and AI servers](docs/LOCAL_AI.md) directly;
   `sudo open-speaker doctor` checks the whole setup.

## Repository

| Path | |
|---|---|
| [`esphome/`](esphome/) | The ESP32-S3 brain: ESPHome configuration and sounds |
| [`firmware/`](firmware/) | The Raspberry Pi brain: the `open-speaker` Python package and its tests |
| [`hardware/enclosure/`](hardware/enclosure/) | Parametric OpenSCAD enclosure, export script |
| [`hardware/schematics/gpio_pinout.md`](hardware/schematics/gpio_pinout.md) | Wiring for both brains |
| [`hardware/speaker_specs/`](hardware/speaker_specs/) | Measuring the salvaged drivers |
| [`scripts/`](scripts/) | Installer for the Pi, and checks that keep the docs and sounds in step |
| [`config/`](config/) | ALSA, boot configuration and systemd unit (used by the installer) |
| [`server/`](server/) | Docker Compose for Whisper, Piper and Ollama |
| [`docs/`](docs/) | Build guide, BOM and shopping list, Home Assistant and local AI guides |
| [`insignia_ns_cspgasp_rebuild/`](insignia_ns_cspgasp_rebuild/) | Archive: the first plan, which reused the original case and display board |

Both brains live side by side on one branch, and CI builds and checks both on
every push.

## Status

- **Pi software**: complete for the features above and covered by unit tests. They
  run against fake audio devices, fake GPIO and fake Home Assistant and Wyoming
  servers.
- **ESP32-S3 software**: the ESPHome configuration validates and CI compiles it;
  it hasn't run on a speaker yet.
- **Enclosure**: modelled and checked in OpenSCAD for printability, part
  clearances and assembly order, with either brain. It hasn't been printed yet,
  and the driver dimensions are estimates from the teardown photos until measured.
- **Electronics**: the wiring follows the parts' datasheets; the full build is
  still to be bench tested.

The background and design decisions are in
[NS-CSPGASP_Rebuild_Plan.md](NS-CSPGASP_Rebuild_Plan.md).

## License

MIT, see [LICENSE](LICENSE).
