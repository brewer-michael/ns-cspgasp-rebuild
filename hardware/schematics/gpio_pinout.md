# Wiring

The speaker has one of two brains: an **ESP32-S3** (ESPHome, the default) or a
**Raspberry Pi Zero 2 W** (the Linux firmware). Everything else wires the same way
to either one; only the pins on the brain differ. Each brain has its own pin table
below, and the sections after them apply to both.

The names used in the shared sections:

| Signal | What it is |
|---|---|
| `AMP_BCLK`, `AMP_LRCLK`, `AMP_DOUT` | I2S bit clock, frame clock and data to the amplifiers |
| `MIC_BCLK`, `MIC_LRCLK`, `MIC_DIN` | I2S bit clock, frame clock and data from the microphones |
| `SDA`, `SCL` | I2C to the OLED |
| `LED` | Data to the WS2812B status LEDs |

## ESP32-S3

ESP32-S3-DevKitC-1 (N8R8). Everything is on its **J1** header, the side with the
`5V` pin, and the board is labelled with the GPIO numbers. The pins are the
defaults in [`esphome/open-speaker.yaml`](../../esphome/open-speaker.yaml); change
them with its substitutions.

| GPIO | J1 pin | Signal | Connects to |
|---|:-:|---|---|
| 5V | 21 | Power in | USB-C breakout VBUS (5 V) |
| 3V3 | 1 | 3.3 V out | Microphones, OLED |
| GND | 22 | Ground | Everything |
| GPIO4 | 4 | `AMP_LRCLK` | Both amps `LRC` |
| GPIO5 | 5 | `AMP_BCLK` | Both amps `BCLK` |
| GPIO6 | 6 | `AMP_DOUT` | Both amps `DIN` |
| GPIO7 | 7 | `LED` | WS2812B `DIN` |
| GPIO15 | 8 | `MIC_LRCLK` | Both mics `WS` |
| GPIO16 | 9 | `MIC_BCLK` | Both mics `SCK` |
| GPIO17 | 10 | `MIC_DIN` | Both mics `SD` (shared) |
| GPIO8 | 12 | `SDA` | OLED `SDA` |
| GPIO9 | 15 | `SCL` | OLED `SCL` |
| GPIO11 | 17 | Button | Volume up |
| GPIO12 | 18 | Button | Volume down |
| GPIO13 | 19 | Button | Action: talk / stop / snooze |
| GPIO14 | 20 | Button | Microphone mute (back panel) |

The microphones and the amplifiers each have their own clocks here, because the
ESP32-S3 runs them on separate I2S buses. None of these pins are strapping pins,
and GPIO10 and GPIO18 stay free.

**Power: one source at a time.** The DevKitC takes 5 V on its `5V` pin from the
USB-C breakout. Unplug the speaker's supply before you connect the DevKitC's own
USB port for flashing.

The DevKitC sits pins down on the printed `esp32_cradle`, with its USB ports towards
the back opening. The harness plugs onto its pins from below: use female jumper
housings, as on the Pi.

## Raspberry Pi Zero 2 W

BCM GPIO numbers. The pins match the defaults in `/etc/open-speaker/config.yaml`;
buttons and the display pins can be changed there, and `open-speaker check-config`
refuses conflicting pins. On the Pi, the amplifiers and microphones share one I2S
bus, so `AMP_BCLK` is `MIC_BCLK` and `AMP_LRCLK` is `MIC_LRCLK`.

| GPIO | Pin | Signal | Connects to |
|---|:-:|---|---|
| 5V | 2, 4 | Power in | USB-C breakout VBUS (5 V) |
| 3V3 | 1, 17 | 3.3 V out | Microphones, OLED |
| GND | 6, 9, 14, 20, 25, 30, 34, 39 | Ground | Everything |
| GPIO18 | 12 | `AMP_BCLK` = `MIC_BCLK` | Both amps `BCLK`, both mics `SCK` |
| GPIO19 | 35 | `AMP_LRCLK` = `MIC_LRCLK` | Both amps `LRC`, both mics `WS` |
| GPIO21 | 40 | `AMP_DOUT` | Both amps `DIN` |
| GPIO20 | 38 | `MIC_DIN` | Both mics `SD` (shared) |
| GPIO2 | 3 | `SDA` | OLED `SDA` |
| GPIO3 | 5 | `SCL` | OLED `SCL` |
| GPIO10 | 19 | `LED` (SPI MOSI) | WS2812B `DIN` |
| GPIO17 | 11 | Button | Volume up |
| GPIO27 | 13 | Button | Volume down |
| GPIO5 | 29 | Button | Action: talk / stop / snooze |
| GPIO22 | 15 | Button | Microphone mute (back panel) |
| GPIO12 | 32 | PWM | Volume LED through 220 Ω (optional) |
| GPIO16 | 36 | **Reserved** | Claimed by the sound card overlay: leave unconnected |
| GPIO23 / 24 | 16 / 18 | TM1637 `CLK` / `DIO` | Only if you use the TM1637 display instead of the OLED |

```
                 Pi Zero 2 W header (component side up, pin 1 top left)

        3V3 mics,OLED  [ 1] [ 2]  5V in (USB-C)
             OLED SDA  [ 3] [ 4]  5V
             OLED SCL  [ 5] [ 6]  GND
                       [ 7] [ 8]
                  GND  [ 9] [10]
       volume up (17)  [11] [12]  I2S BCLK (18)
     volume down (27)  [13] [14]  GND
            mute (22)  [15] [16]  (TM1637 CLK, 23)
                  3V3  [17] [18]  (TM1637 DIO, 24)
    LEDs, SPI MOSI(10) [19] [20]  GND
                       [21] [22]
                       [23] [24]
                  GND  [25] [26]
                       [27] [28]
           action (5)  [29] [30]  GND
                       [31] [32]  volume LED (12)
                       [33] [34]  GND
      I2S LRCLK (19)   [35] [36]  reserved (16)
                       [37] [38]  I2S DIN from mics (20)
                  GND  [39] [40]  I2S DOUT to amps (21)
```

## Buttons

Each button connects its GPIO to GND when pressed. Both brains use their internal
pull-ups, so no resistors are needed.

## Amplifiers (2 × MAX98357A)

Both amps get the same I2S signals. The voltage on each amp's `SD` pin picks its
channel:

| `SD` voltage | Output |
|---|---|
| above 1.4 V | left channel |
| 0.77 – 1.4 V | right channel |
| 0.16 – 0.77 V | (left + right) / 2 |
| below 0.16 V | shut down |

The chip pulls `SD` down with 100 kΩ inside.

| Amp pin | Left amp | Right amp |
|---|---|---|
| `VIN` | 5 V | 5 V |
| `GND` | GND | GND |
| `BCLK` / `LRC` / `DIN` | `AMP_BCLK` / `AMP_LRCLK` / `AMP_DOUT` | `AMP_BCLK` / `AMP_LRCLK` / `AMP_DOUT` |
| `GAIN` | not connected (9 dB) | not connected (9 dB) |
| `SD` | straight to `VIN` | resistor to `VIN`, see below |
| `+` / `−` | left driver | right driver |

**The right amp's resistor depends on the board.** Adafruit's breakout (3006)
already has 1 MΩ from `SD` to `VIN`. Use **680 kΩ** there, in parallel with it,
for about 1.0 V. On boards without that pull-up, use **390 kΩ**. Measure `SD` to
GND with the amp powered: you want about 1.0 V. Then play something with a clear
left and right (on the Pi: `speaker-test -D default -c 2 -t wav`) and check that
each side comes from the right driver.

Never connect a speaker terminal to ground: the outputs are bridged.

## Microphones (2 × INMP441)

| Mic pin | Left mic | Right mic |
|---|---|---|
| `VDD` | 3.3 V | 3.3 V |
| `GND` | GND | GND |
| `SCK` | `MIC_BCLK` | `MIC_BCLK` |
| `WS` | `MIC_LRCLK` | `MIC_LRCLK` |
| `SD` | `MIC_DIN` | `MIC_DIN` (shared) |
| `L/R` | GND | 3.3 V |

Each mic drives `SD` only during its own half of the frame, so the two share one
wire. The Pi records both as one stereo stream and mixes them
(`audio.input.channel: mix`) or uses one. The ESP32-S3 listens with the left one.

## Display

**1.3" OLED (SH1106, I2C, default).** `VCC` to 3.3 V, `GND`, `SDA`, `SCL`. Its
address is usually 0x3C; on the Pi, check with `i2cdetect -y 1`. The 0.96" SSD1306
and 2.42" SSD1309 modules wire the same way (`display.oled.driver` on the Pi). The
2.42" boards often come set up for SPI and need resistors moved for I2C: see the
seller's notes.

**TM1637 4-digit display (Pi only).** `CLK` to GPIO23, `DIO` to GPIO24, `VCC` to
**3.3 V only**. These modules pull their data lines up to their own supply, and the
Pi's pins are not 5 V tolerant.

## Status LEDs (WS2812B)

`DIN` to `LED`, `5V` and `GND`, three LEDs from a 60 LED/m strip. Both brains send
a 3.3 V signal, which is below the WS2812B's specified input level at 5 V. Short
wires usually work anyway. If the colours flicker, feed the strip's 5 V through a
1N4001 diode (about 4.3 V), or add a 74AHCT125 level shifter.

## Power

```
USB-C breakout VBUS (5 V, 3 A supply)
 ├── the brain's 5V pin ..................... ESP32-S3 up to ~0.35 A, Pi up to ~0.5 A
 ├── left amp VIN ........................... up to ~0.7 A at full volume
 ├── right amp VIN .......................... up to ~0.7 A at full volume
 └── WS2812B strip .......................... up to 60 mA per LED at full white
the brain's 3.3 V pin ── mics, OLED ........ ~25 mA
```

Take each amp's power straight from the USB-C breakout, not through the brain, and
join all grounds at the breakout. Use 22 AWG for 5 V and ground to the amps;
26–28 AWG silicone wire is fine for signals.
