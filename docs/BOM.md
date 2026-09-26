# Bill of materials

Everything except the two drivers is new, off-the-shelf and replaceable. Prices
are rough US retail; generic parts from AliExpress cost less.

## Electronics

| Part | Qty | Notes | ≈ USD |
|---|:-:|---|--:|
| Raspberry Pi Zero 2 W | 1 | The "WH" version comes with the header soldered | 15 |
| microSD card, 16–32 GB, A1 | 1 | Raspberry Pi OS Lite, 64-bit | 7 |
| MAX98357A I2S amplifier | 2 | [Adafruit 3006](https://www.adafruit.com/product/3006) or generic modules; 3 W into 4 Ω each | 12 |
| INMP441 I2S microphone module | 2 | 14 × 14 mm boards | 8 |
| USB-C breakout | 1 | [Adafruit 4090](https://www.adafruit.com/product/4090) (20.4 × 14.2 mm) or similar | 3 |
| USB-C power supply, 5 V 3 A | 1 | The official Raspberry Pi 15 W supply is ideal | 10 |
| Resistor for the right amp's `SD` pin | 1 | 680 kΩ for Adafruit boards, 390 kΩ for boards without a pull-up ([why](../hardware/schematics/gpio_pinout.md#amplifiers-2--max98357a)) | 0.10 |
| **Display**: 1.3" 128 × 64 I2C OLED, SH1106 | 1 | Yellow looks like the original's amber digits. Alternatives: 2.42" SSD1309 (bigger window) or a TM1637 4-digit display | 8 |
| WS2812B LED strip, 60 LED/m, 10 mm, non-waterproof | 3 LEDs | The status light in the waist | 3 |
| 6 × 6 × 5 mm tactile switches, through-hole | 4 | Volume up, volume down, action, microphone mute | 2 |
| Perfboard, 2.54 mm pitch | small piece | Holds the switches | 1 |
| 5 mm LED + 220 Ω resistor | 1 | Optional volume LED; the enclosure has no hole for it by default | 0.50 |
| 1N4001 diode | 1 | Optional, only if the LEDs flicker ([wiring](../hardware/schematics/gpio_pinout.md#status-leds-ws2812b)) | 0.10 |
| Silicone wire, 26 AWG and 22 AWG | | Signals and 5 V | 8 |

## Enclosure

See [hardware/enclosure/README.md](../hardware/enclosure/README.md) for what each
part is for.

| Part | Qty | ≈ USD |
|---|:-:|--:|
| PETG filament | ~450 g, plus a little white or natural for the light diffuser | 10 |
| Smoked grey acrylic, 2 mm | 51.5 × 29.5 mm window | 3 |
| M3 brass heat-set inserts (4.0 mm hole) | 6 | 3 |
| M3 × 8 countersunk screws | 14 | 2 |
| M3 × 10 countersunk screws | 4 | 1 |
| M2.5 × 6 pan head screws | 4 | 1 |
| M2 × 6 self-tapping screws | 4 | 1 |
| Closed-cell foam tape, 1 mm × 6 mm | ~0.7 m | 5 |
| Rubber bumpers, 10 mm | 4 | 2 |
| Polyester fibre fill | a handful | 1 |

## From the original speaker

| Part | Qty | Notes |
|---|:-:|---|
| Full-range drivers, ~52 mm, 4 Ω | 2 | Measure them first: [measurements.md](../hardware/speaker_specs/measurements.md) |
| Passive radiator | 0–1 | Only for `bass_mode = "passive_radiator"` |

**Total: about $110** for the speaker. You also need an always-on machine on your
network for speech recognition and the language model. Home Assistant's own box is
enough for Speech-to-Phrase and Piper. See [LOCAL_AI.md](LOCAL_AI.md).

## Tools

Soldering iron (also for the heat-set inserts), multimeter, wire strippers, small
screwdrivers, hot glue, and a 3D printer with at least 160 mm of Z height.
