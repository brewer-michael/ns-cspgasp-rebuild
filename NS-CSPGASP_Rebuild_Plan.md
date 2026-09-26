# NS-CSPGASP rebuild: plan and design decisions

How the project got here, what it is trying to do, and why the parts and software
are what they are. The build itself is in [docs/ASSEMBLY_GUIDE.md](docs/ASSEMBLY_GUIDE.md).

## History

1. **Reuse the case and display board** (archived in
   [`insignia_ns_cspgasp_rebuild/`](insignia_ns_cspgasp_rebuild/)). The idea was
   to keep the Insignia enclosure and its "Condor" top board (LED clock and touch
   controls) and drive them from a Pi through an adapter for the ribbon cable.
   The main board is locked down with secure boot, and splicing the ribbon bricked
   the unit.
2. **Teardown and new spec** (the `reverse-engineer` branch). Only the two drivers
   are worth keeping. New electronics, new enclosure.
3. **v2** (this branch). The software is rewritten as an installable package with
   a voice pipeline for Home Assistant and local models. The enclosure is
   redesigned as a tower on the smaller, mains-powered NS-CSPGASP's footprint
   (96 × 96 × 151.6 mm): left and right drivers, a bass chamber, and the clock
   display high on the front. Buttons replace the touch controls.

## Goals

- Open source, and built only from parts anyone can buy. The drivers are the only
  thing reused.
- A good Home Assistant voice speaker: wake word, voice commands, announcements.
- Speech recognition and AI models on the local network, configurable, with no
  cloud needed.
- Still a clock: the time and temperature always on the display; timers and
  alarms that work offline and survive reboots.
- Roughly the original's footprint and loudness (about 90 dB), in stereo.

## Decisions

| Topic | Decision | Why |
|---|---|---|
| Computer | Raspberry Pi Zero 2 W | Linux, Wi-Fi, enough for a wake word; small and cheap |
| Where speech runs | Wake word on the speaker, everything else on the network | Even Whisper tiny takes seconds per command on a Zero 2 W; see [docs/LOCAL_AI.md](docs/LOCAL_AI.md) |
| Wake word | microWakeWord by default; openWakeWord or a Wyoming server optional | microWakeWord is small enough for the Zero 2 W with room to spare |
| Voice pipeline | Home Assistant's Assist pipeline over its WebSocket API, or the speaker's own pipeline to Wyoming and OpenAI-compatible servers | Home Assistant users get everything from their existing pipeline; others can point at any common local server |
| On-device commands | Timers, alarms, stop, snooze and volume are handled before the pipeline | Instant, and they keep working when the network is down |
| Audio out | 2 × MAX98357A on one I2S bus; `SD` voltage selects left or right | Digital all the way to the amps, no analog noise; 3 W each into the 4 Ω drivers |
| Audio in | 2 × INMP441 on the same I2S bus | Built in, no USB; the two mics share one data line |
| Sound card | `googlevoicehat-soundcard` overlay | Plays and records on the same I2S port. `hifiberry-dac`, from the earlier plan, can only play. It claims GPIO16, so that pin stays free. |
| Sharing the sound card | ALSA `dmix`/`dsnoop` with a `Master` softvol, from [config/asound.conf](config/asound.conf) | Wake word, replies and music share the card; volume works without a hardware mixer |
| Display | 1.3" I2C OLED by default; 2.42" OLED or TM1637 optional | Shows the original's layout (big time, temperature underneath, AL/PM); the OLED is sharp behind a smoked window |
| Status light | WS2812B driven over SPI | No root access or kernel PWM needed |
| GPIO library | gpiozero with the lgpio backend | RPi.GPIO's edge detection no longer works on current kernels |
| Buttons | Physical: volume −/+, action (talk/stop/snooze), microphone mute | Touch pads were unreliable on the original |
| Enclosure | One-piece PETG body, round side grilles, shared tuned bass chamber, clamp-ring driver mounts, flush top plate, screwed back panel | See [hardware/enclosure/README.md](hardware/enclosure/README.md#design-notes) |
| Chamber | One shared, ported chamber instead of two sealed ones | More bass from small drivers; at low frequencies both play the same signal anyway |

Issues that were open on the `reverse-engineer` branch are now settled:

- **Microphones**: the internal I2S INMP441 pair everywhere; the USB microphone
  option is gone.
- **Full duplex**: a single `googlevoicehat-soundcard` overlay replaces
  `hifiberry-dac`.
- **Driver dimensions**: still to be measured. The enclosure is parametric, and
  the clamp-ring mount works whether or not the drivers have screw holes.

## Still to verify on real hardware

- The drivers' dimensions and the port tuning (120 Hz by default) against the
  real drivers.
- The right amplifier's `SD` resistor on the boards actually bought (target about
  1.0 V).
- The OLED's active-area offset on the chosen module (`display` presets in
  `main_body.scad`).
- Microphone gain and the wake-word threshold inside the finished enclosure.
