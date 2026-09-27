# Build guide

From an Insignia NS-CSPGASP on the bench to a working Open Speaker. Parts are in
[BOM.md](BOM.md), wiring in
[gpio_pinout.md](../hardware/schematics/gpio_pinout.md), and the enclosure in
[hardware/enclosure/README.md](../hardware/enclosure/README.md).

Everything is tested on the desk before it goes into the enclosure.

## 1. Take the drivers out of the original

1. Peel off the rubber feet and remove the screws under them, then release the
   clips around the seam with a plastic pry tool.
2. Inside is a plastic speaker box that holds both drivers, and the Condor boards
   on top of it. Unplug the speaker cables from the main board.
3. Unscrew the halves of the speaker box. The drivers sit in round seats between
   the halves, with rubber rings around them. Lift them out without touching the
   cones. If there's a passive radiator (a flat disc with a rubber surround), keep
   it too.
4. Mark each driver's + terminal (usually red, or a dot or "+" on the frame).

## 2. Measure and test the drivers

Fill in [measurements.md](../hardware/speaker_specs/measurements.md): frame
diameter, cone diameter, the widest part behind the flange, flange thickness and
depth. These go into the enclosure model (step 6).

- Resistance across the terminals: about 3.2 Ω for a 4 Ω driver.
- Polarity: touch a 1.5 V battery to the terminals, + to +. The cone should move
  outwards.

## 3. Set up the brain

The speaker has one of two brains ([which one?](../README.md#two-brains)). The
wiring is the same for both apart from the pins on the brain itself.

### ESP32-S3

Flash it before anything is wired to it. Follow
[esphome/README.md](../esphome/README.md#install): the ESPHome Device Builder in
Home Assistant builds the firmware and flashes it over USB, and after that it
updates over Wi-Fi.

### Raspberry Pi Zero 2 W

1. With [Raspberry Pi Imager](https://www.raspberrypi.com/software/), write
   **Raspberry Pi OS Lite (64-bit)**. In the settings, set the hostname
   (`open-speaker`), your Wi-Fi, a user, SSH and your time zone (the clock uses it).
2. Boot the Pi and log in: `ssh <user>@open-speaker.local`.
3. Install:

   ```sh
   sudo apt install -y git
   git clone -b v2 https://github.com/brewer-michael/ns-cspgasp-rebuild.git
   sudo ns-cspgasp-rebuild/scripts/install.sh
   sudo reboot
   ```

   The installer sets up the sound card, I2C and SPI, installs the software into
   `/opt/open-speaker`, writes `/etc/open-speaker/config.yaml` and a systemd
   service, and turns off Wi-Fi power saving. It is safe to run again to update.

## 4. Test on the desk

Wire everything on a half-size breadboard with jumper wires
([desk test parts](BOM.md#desk-test)) as in
[gpio_pinout.md](../hardware/schematics/gpio_pinout.md). Each shared line, such as
a clock that goes to both amplifiers, gets its own breadboard row. Power the brain
through the USB-C breakout, not its own USB port, so the amplifiers get their
current straight from the supply.

Whichever the brain, start with one amplifier and one driver, then add the second
amplifier. With the resistor on the right amp's `SD` pin, measure `SD` to ground:
about 1.0 V (0.77–1.4 V).

### ESP32-S3

Unplug its USB cable before you power it from the breakout. Watch its log over
Wi-Fi: **Logs** in the Device Builder, or `esphome logs esphome/open-speaker.yaml`.

- **Display and light.** The clock shows "--:--" and "net" until Home Assistant
  connects (step 5), then the time. The light is dim blue once it's ready.
- **Buttons.** − and + show "Vol 40" and so on; the back button shows "mic off".
- **Sound.** Each volume press ticks. Play something to the speaker's media player
  in Home Assistant to check both drivers.
- **Microphones.** Say "Okay Nabu": the log shows the wake word and the light turns
  green.

### Raspberry Pi Zero 2 W

**Sound.**

```sh
aplay -l                                  # the card is "sndrpigooglevoi"
speaker-test -D default -c 2 -t wav -l 1  # says "front left", "front right"
```

Check that each side says its own name.

**Microphones.**

```sh
sudo open-speaker test-mic --seconds 5    # shows the level while you talk
```

A silent channel usually means a swapped `L/R` pin or a loose `SD` wire.

**Display, LEDs, buttons.** `i2cdetect -y 1` should show the OLED at `3c`. Then
run the full check:

```sh
sudo open-speaker doctor
```

It checks the sound devices, the microphones, the wake word model, the display,
the LEDs, the GPIO pins and every server in the configuration.

## 5. Connect it to Home Assistant and your servers

**ESP32-S3:** add it in Home Assistant and choose its Assist pipeline:
[HOME_ASSISTANT.md](HOME_ASSISTANT.md#esp32-s3-speaker). The pipeline decides
which speech and language servers answer.

**Pi:** follow [HOME_ASSISTANT.md](HOME_ASSISTANT.md) (token, Assist pipeline), or
[LOCAL_AI.md](LOCAL_AI.md) to run without Home Assistant. Then:

```sh
sudo open-speaker doctor                  # everything OK?
sudo systemctl start open-speaker
journalctl -u open-speaker -f             # watch the log
```

Say **"Okay Nabu"**, wait for the chime, then try "what time is it?" or "set a
timer for one minute".

## 6. Print the enclosure

Enter your driver measurements, export and print:
[hardware/enclosure/README.md](../hardware/enclosure/README.md). Everything prints
in PETG without supports.

## 7. Build it

Follow the assembly order in the
[enclosure README](../hardware/enclosure/README.md#assembly). A few tips:

- Make the wiring harness before you start: the brain sits on the deck at the
  bottom of the head. The display (front), buttons and microphones (top plate),
  the mute button and USB-C (back panel) need about 12–15 cm of wire each.
  Female jumper housings on the brain's pins make the top plate and back panel
  removable.
- Seal the chamber well: foam tape on the deck ledge and the back frame, and hot
  glue in the deck's wire hole. Leaks make the bass weak and can whistle at the
  port.
- Test again before closing the back panel (on the Pi: `sudo open-speaker doctor`).

## Using it

| | |
|---|---|
| **Wake word** | "Okay Nabu" (change it in the configuration: `wake_word` on the ESP32-S3) |
| **Action button** (top, middle) | Tap: talk, or stop whatever is happening. When an alarm rings: tap to snooze, hold to turn it off |
| **− / +** | Volume; hold to keep changing |
| **Mute** (back) | Microphone off and on. The light turns dim red and the display says "mic off" |

**Timers and alarms.**

- **ESP32-S3.** Set timers by voice: "set a timer for 10 minutes". Home Assistant
  keeps track of them and the speaker rings. Set the alarm in Home Assistant
  (**Alarm**, **Alarm time**, **Alarm days** on the device page). It rings from the
  speaker's own clock, so it works while Home Assistant is down.
- **Pi.** The speaker handles these itself, even when your server is down: "set a
  timer for 10 minutes", "how much time is left?", "wake me up at 6:30 on
  weekdays", "what alarms do I have?", "cancel my alarm", "stop", "snooze",
  "set the volume to 4".

Everything else goes to Home Assistant or your language model: "turn on the
kitchen lights", "is the front door locked?", "how far away is the moon?".

**Display.** It always shows the time and the temperature. The volume, "mic off"
or a timer's countdown take the temperature's place for a moment. "AL" means an
alarm is set. "net" in place of the temperature means Home Assistant or your
voice servers can't be reached; alarms still ring. It dims from 22:00 to 07:00.

![Clock face examples](images/display.png)

**Light.** Dim blue: ready. Green: listening. Pulsing cyan: thinking. Pulsing blue: speaking.
Pulsing orange: alarm or timer. Dim red: microphone muted. Red: error.

## Troubleshooting

| Problem | Check |
|---|---|
| ESP32-S3: "net" on the display | Is it online in Home Assistant? Check Wi-Fi and the API key in its YAML, and the log |
| ESP32-S3: no sound | The `amp_*_pin` settings match your wiring; play something to its media player |
| ESP32-S3: wake word never triggers | The left mic's `L/R` to GND and `SD` to GPIO17; raise `mic_gain` |
| Pi: no sound card in `aplay -l` | Reboot after installing; `dtoverlay=googlevoicehat-soundcard` in `/boot/firmware/config.txt` |
| Both sides play the same, or one is silent | The `SD` voltages (step 4); left `SD` straight to 5 V |
| Crackles at high volume | Supply too weak, or the amps powered through the brain |
| Pi: microphones silent | `L/R` pins (left to GND, right to 3.3 V); `SD` of both mics to GPIO20 |
| Pi: wake word never triggers | `sudo open-speaker test-mic`: the level should rise clearly when you talk; try `audio.input.gain_db: 10` |
| Pi: wake word triggers by itself | Set `wake.threshold` a little higher |
| OLED blank | Its address is usually 0x3C (on the Pi: `i2cdetect -y 1`; set `display.oled.address`). The 0.96" type needs `driver: ssd1306` on the Pi |
| LEDs flicker or show wrong colours | The diode or level shifter from the wiring guide; on the Pi also `core_freq=250` in config.txt |
| Pi: "Authentication failed" | The token in `/etc/open-speaker/secrets.env`, then `sudo systemctl restart open-speaker` |
| Pi: "net" on the display | `sudo open-speaker doctor` shows which server can't be reached |
| Slow answers | See "Making it quick" in [LOCAL_AI.md](LOCAL_AI.md#making-it-quick) |
