# Bill of materials

Everything except the two drivers is bought new. Prices are in US dollars, checked
on 26 September 2026, without tax or shipping. A plain price is the store's listed
price that day. **≈** marks an estimate where the listed price couldn't be
confirmed: check it in the store.

To shop, open [`shopping-list.html`](shopping-list.html) from your copy of the
repository in a browser. It has every part with its store link and searches at
other stores to compare prices. It also works out what to buy for any number of
speakers and lets you tick parts off as you buy them.

| | Per speaker | First build |
|---|--:|--:|
| [Electronics](#electronics) | ≈ $69.64 | ≈ $139.57 |
| [Enclosure hardware](#enclosure-hardware) | ≈ $3.99 | ≈ $58.86 |
| [Filament](#filament) | $13.10 | $28.79 |
| **Speaker** | **≈ $87** | **≈ $227** |
| [Desk test parts](#desk-test) (reusable) | | ≈ $12.90 |
| [Shop supplies](#shop-supplies) | | ≈ $21.00 |
| **Everything** | | **≈ $261** |

*Per speaker* counts only what one speaker uses. *First build* is what you pay,
because screws, wire, filament and several modules only come in packs. Of the
$227, $145 is estimated, mostly Amazon packs. A second speaker costs about $65
more: a Pi, microSD card, amplifiers, USB-C breakout, power supply and switches,
plus another pack of microphones.

## Electronics

| Part | Qty | Buy | Price | Per speaker |
|---|:-:|---|--:|--:|
| Raspberry Pi Zero 2 WH (SC0721, header soldered on) | 1 | [DigiKey](https://www.digikey.com/en/products/detail/raspberry-pi/SC0721/24627135) | $18.00 | $18.00 |
| microSD card: SanDisk Ultra 32 GB A1 (SDSQUA4-032G-GN6MA) | 1 | [Amazon](https://www.amazon.com/dp/B08GY9NYRM) | ≈ $9 | ≈ $9.00 |
| Adafruit MAX98357A I2S amplifier (3006) | 2 | [Adafruit](https://www.adafruit.com/product/3006) | $5.95 each | $11.90 |
| INMP441 I2S microphone module: AITRIP, pack of 3 | 2 | [Amazon](https://www.amazon.com/dp/B0972XP1YS) | ≈ $14 | ≈ $9.33 |
| Adafruit USB-C breakout (4090) | 1 | [Adafruit](https://www.adafruit.com/product/4090) | $2.95 | $2.95 |
| Raspberry Pi 15 W USB-C power supply, US plug, black | 1 | [PiShop](https://www.pishop.us/product/raspberry-pi-15w-power-supply-us-black/) | ≈ $8 | ≈ $8.00 |
| 1.3" OLED, 128 × 64, SH1106, I2C, white: Hosyond, pack of 5 | 1 | [Amazon](https://www.amazon.com/dp/B0C3L7N917) | ≈ $20 | ≈ $4.00 |
| WS2812B strip, 60 LED/m, IP30, black PCB, 1 m: BTF-LIGHTING | 3 LEDs | [Amazon](https://www.amazon.com/dp/B01CDTED80) | ≈ $14 | ≈ $0.70 |
| Omron B3F-1000 tactile switch, 6 × 6 × 4.3 mm | 4 | [DigiKey](https://www.digikey.com/en/products/detail/omron-electronics-inc-emc-div/B3F-1000/33150) | $0.35 each | $1.40 |
| 680 kΩ resistor, ¼ W (Stackpole CFM14JT680K) | 1 | [DigiKey](https://www.digikey.com/en/products/detail/stackpole-electronics-inc/CFM14JT680K/1742269) | ≈ $0.10 | ≈ $0.10 |
| 1N4001G diode (onsemi) | 1 | [DigiKey](https://www.digikey.com/en/products/detail/onsemi/1N4001G/1485468) | $0.27 | $0.27 |
| Perfboard: ELEGOO kit of 32 double-sided boards | 2 boards | [Amazon](https://www.amazon.com/dp/B072Z7Y19F) | ≈ $12 | ≈ $0.75 |
| Jumper wires, female/female, 40 × 150 mm (Adafruit 266) | ~10 | [Adafruit](https://www.adafruit.com/product/266) | $3.95 | $0.99 |
| Silicone wire, 26 AWG, 6 colours | ~4 m | [Amazon](https://www.amazon.com/dp/B07G2LRX68) | ≈ $13 | ≈ $1.50 |
| Silicone wire, 22 AWG, red and black | ~1.5 m | [Amazon](https://www.amazon.com/dp/B07ZFP8KCN) | ≈ $11 | ≈ $0.75 |

- **Pi.** Also at [PiShop](https://www.pishop.us/product/raspberry-pi-zero-2w-with-headers/)
  and [Adafruit](https://www.adafruit.com/product/6008) ($19.80, out of stock on
  26 September). The Zero 2 W without the header is $15, but then you solder the
  header yourself.
- **Microphones.** The same AITRIP pack of 3 was $14.43 on
  [eBay](https://www.ebay.com/itm/235775726409).
- **Power supply.** The same supply is [Adafruit 4298](https://www.adafruit.com/product/4298),
  $8.74, but it was out of stock on 26 September. Any 5 V 3 A USB-C supply works.
- **OLED.** The enclosure is drawn for this module: a 35.4 × 33.5 mm board with a
  29.42 × 14.70 mm active area. Other 1.3" SH1106 I2C modules are usually the same
  size, but check before you buy one.
- **Switches.** The top plate and back panel are drawn for 4.3 mm switches. For a
  different switch, set `switch_height` in the model to its height from the board
  to the top of the plunger.
- **Resistor.** 680 kΩ is for the Adafruit amplifier, which already has a 1 MΩ
  pull-up. Other MAX98357A boards need
  [390 kΩ](https://www.digikey.com/en/products/detail/stackpole-electronics-inc/CF14JT390K/1741414)
  instead ([why](../hardware/schematics/gpio_pinout.md#amplifiers-2--max98357a)).
- **Diode.** Only needed if the LEDs flicker
  ([wiring](../hardware/schematics/gpio_pinout.md#status-leds-ws2812b)), but at
  $0.27 it is cheaper than a second order.
- **Perfboard.** The three top switches go on a 50 × 12 mm strip cut from one of
  the 2 × 8 cm boards, the mute switch on a 24 × 14 mm piece.
- **Jumper wires.** Cut in half, they give the harness female housings for the
  Pi's header, so the top plate and back panel stay removable.

## Enclosure hardware

| Part | Qty | Buy | Price | Per speaker |
|---|:-:|---|--:|--:|
| Heat-set inserts, M3 × 5.7 mm: ruthex, pack of 100 | 6 | [Amazon](https://www.amazon.com/dp/B08BCRZZS3) | $9.49 | $0.57 |
| Countersunk hex socket screws, M3 × 8, 10 and 12 mm, 100 each: uxcell | 14 × M3 × 8, 4 × M3 × 10 | [Amazon](https://www.amazon.com/dp/B0C6LQ3B5W) | ≈ $11 | ≈ $0.66 |
| Self-tapping pan head screws, M2 and M2.6: kit of 400 | 4 × M2 × 6, 4 × M2.6 × 6 | [Amazon](https://www.amazon.com/dp/B07VQZXGH2) | ≈ $9 | ≈ $0.18 |
| Rubber feet: 3M Bumpon SJ5312, 12.7 × 3.6 mm, pack of 56 | 4 | [Amazon](https://www.amazon.com/dp/B000NG60SW) | ≈ $10 | ≈ $0.71 |
| Closed-cell EVA foam tape, single-sided, 1 mm × 5 mm × 5 m | ~1 m | [Amazon](https://www.amazon.com/dp/B0FMF21TZD) | ≈ $7 | ≈ $1.40 |
| Smoked acrylic sheet, 1/16" (1.5 mm), 12 × 12", #2074 | one 51.5 × 29.5 mm window | [eBay](https://www.ebay.com/itm/222235546514) | ≈ $7 | ≈ $0.25 |
| Polyester fibre fill: Poly-Fil, 12 oz | a handful | [Walmart](https://www.walmart.com/ip/26678911) | $5.37 | $0.22 |

- **Inserts.** They go into 4.0 mm holes, the size in the model (`insert_diameter`).
- **M2.6 screws** hold the Pi on its standoffs; M2.5 × 6 machine screws work too.
  The M2 screws hold the two switch boards.
- **Feet.** The recesses underneath are 13.2 mm across, for these 12.7 mm feet.
- **Foam tape.** The seal gaps in the model are drawn for 1 mm foam; thicker tape
  won't compress enough. [uxcell 1 mm × 10 mm](https://www.amazon.com/dp/B01L6TE0UO)
  works too if you cut it narrower.
- **Acrylic.** #2074 is the darker smoke and hides the display best when it is off;
  #2064 is lighter. Measure your sheet and set `window_thickness` in the model to
  its thickness (1.6 mm by default) so the window sits flush. One sheet makes about
  50 windows. [Canal Plastics](https://www.canalplastic.com/products/2064-gray-smoke-acrylic-sheet)
  and [T&T Plastic Land](https://www.ttplasticland.com/products/custom-gray-smoke-transparent-2064-acrylic-sheet)
  cut acrylic to size.

## Filament

| Part | Qty | Buy | Price | Per speaker |
|---|:-:|---|--:|--:|
| PETG, 1.75 mm, 1 kg: Prusament Signal White | ~455 g | [Printed Solid](https://www.printedsolid.com/products/prusament-petg-1-75mm-1kg-signal-white) | $28.79 | $13.10 |

About 450 g for the printed parts and 5 g for the light diffuser. The diffuser has
to be white or natural PETG, so a white spool covers everything. For a dark
speaker, print the rest in
[Prusament Jet Black](https://www.printedsolid.com/products/prusament-petg-1-75mm-1kg-jet-black),
also $28.79, and the diffuser in white. Both are sale prices; Signal White is
normally $35.99. Any PETG works.

## Desk test

Reusable parts for testing everything on the desk before it goes into the
enclosure ([build guide, step 4](ASSEMBLY_GUIDE.md#4-test-on-the-desk)).

| Part | Qty | Buy | Price |
|---|:-:|---|--:|
| Half-size breadboard, 400 points (Adafruit 64) | 1 | [Adafruit](https://www.adafruit.com/product/64) | ≈ $5.00 |
| Jumper wires, female/male, 40 × 150 mm (Adafruit 826) | 1 pack | [Adafruit](https://www.adafruit.com/product/826) | $3.95 |
| Jumper wires, male/male, 40 × 150 mm (Adafruit 758) | 1 pack | [Adafruit](https://www.adafruit.com/product/758) | ≈ $3.95 |

## Shop supplies

| Part | Use | Buy | Price |
|---|---|---|--:|
| E6000 clear adhesive, 3.7 oz | Holds the display window | [Amazon](https://www.amazon.com/dp/B007TSYNG8) | ≈ $6 |
| Heat-shrink tubing kit, 3:1, adhesive-lined: Wirefy, 200 pieces | Wire splices | [Amazon](https://www.amazon.com/dp/B089D82FLG) | ≈ $15 |

## Where to order

| Store | Parts | First build |
|---|---|--:|
| Amazon | microSD card, microphones, OLED, LED strip, perfboard, wire, fasteners, feet, foam tape, shop supplies | ≈ $160.49 |
| Adafruit | Amplifiers, USB-C breakout, jumper wires, breadboard | ≈ $31.70 |
| Printed Solid | Filament | $28.79 |
| DigiKey | Pi, switches, resistor, diode | ≈ $19.77 |
| PiShop | Power supply | ≈ $8.00 |
| eBay | Acrylic | ≈ $7.00 |
| Walmart | Fibre fill | $5.37 |

Shipping from seven stores adds up. DigiKey resells most Adafruit products and
PiShop has the Pi too, so check whether you can combine orders.

## From the original speaker

| Part | Qty | Notes |
|---|:-:|---|
| Full-range drivers, ~52 mm, 4 Ω | 2 | Measure them first: [measurements.md](../hardware/speaker_specs/measurements.md) |
| Passive radiator | 0–1 | Only for `bass_mode = "passive_radiator"` |

## Tools

Soldering iron (it also sets the heat-set inserts) and solder, multimeter, wire
strippers, flush cutters, a small Phillips screwdriver, a 2 mm hex key for the M3
screws, a hot glue gun, a craft knife and steel ruler to score the acrylic, a fine
file, and a 3D printer with at least 160 mm of Z height.

## Servers

You also need an always-on machine on your network for speech recognition and the
language model. Home Assistant's own box is enough for Speech-to-Phrase and Piper.
See [LOCAL_AI.md](LOCAL_AI.md).
