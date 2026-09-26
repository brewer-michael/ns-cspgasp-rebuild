# Bill of Materials: Open Hardware Smart Speaker

**Project:** NS-CSPGASP Open Rebuild
**Version:** 2.0 (Open Hardware Pivot)
**Status:** Ready to Order

## Overview

This BOM covers the fully open hardware design that replaces the proprietary Insignia NS-CSPGASP internals. Only the original speakers are reused.

---

## 1. Core Electronics (~$45)

| Component | Qty | Specifications | Recommended Sources | Est. Cost |
|-----------|:---:|----------------|---------------------|----------:|
| **Raspberry Pi Zero 2 W** | 1 | Quad-core, WiFi, BT | [Adafruit 5291](https://www.adafruit.com/product/5291), [Pi Hut](https://thepihut.com/products/raspberry-pi-zero-2-w) | $15.00 |
| **MicroSD Card** | 1 | 32GB, Class 10/A1 | SanDisk Ultra, Samsung EVO | $7.00 |
| **MAX98357A I2S Amp** | 2 | 3W Class-D, I2S input | [Adafruit 3006](https://www.adafruit.com/product/3006), Amazon packs | $12.00 |
| **USB-C Breakout** | 1 | Power input | [Adafruit 4090](https://www.adafruit.com/product/4090) | $3.00 |
| **5V 3A Power Supply** | 1 | USB-C or barrel | Amazon generic, Mean Well | $8.00 |
| **390kΩ Resistor** | 1 | 1/4W through-hole | Any supplier | $0.10 |

---

## 2. Voice Input (~$8-15)

Internal microphone for clean, integrated design matching the original product.

### Recommended: I2S MEMS Microphone (Internal Mount)

| Component | Qty | Specifications | Recommended Sources | Est. Cost |
|-----------|:---:|----------------|---------------------|----------:|
| **INMP441 I2S Mic** | 2 | I2S digital, 24-bit, -26dB sensitivity | [Amazon](https://www.amazon.com/s?k=INMP441), AliExpress | $8.00 |

**Why 2 microphones:**
- Dual-mic allows for beamforming (directional pickup)
- Better noise rejection and echo cancellation
- Matches professional voice assistant designs

### Alternative: SPH0645 I2S Microphone

| Component | Qty | Specifications | Recommended Sources | Est. Cost |
|-----------|:---:|----------------|---------------------|----------:|
| **SPH0645LM4H** | 2 | I2S digital, better SNR than INMP441 | [Adafruit 3421](https://www.adafruit.com/product/3421) | $12.00 |

### Acoustic Considerations for Internal Mounting

- Mount mics on **top of enclosure** (away from speakers)
- Use **small sound ports** (2-3mm holes) with mesh covering
- Add **acoustic isolation gasket** between mic PCB and enclosure
- Keep mic wiring away from power lines to reduce noise

---

## 3. Display & Status LEDs (~$8)

| Component | Qty | Specifications | Recommended Sources | Est. Cost |
|-----------|:---:|----------------|---------------------|----------:|
| **TM1637 4-Digit Display** | 1 | 0.56" 7-segment, white or amber | [Amazon](https://www.amazon.com/s?k=TM1637+display), AliExpress | $3.00 |
| **WS2812B RGB LEDs** | 3-5 | Addressable, 5V | [Adafruit 1938](https://www.adafruit.com/product/1938), strips | $3.00 |
| **Single LED** | 1 | 5mm, any color (volume indicator) | Any | $0.50 |
| **220Ω Resistor** | 1 | For single LED current limit | Any | $0.10 |

---

## 3. Controls (~$2)

| Component | Qty | Specifications | Recommended Sources | Est. Cost |
|-----------|:---:|----------------|---------------------|----------:|
| **Tactile Buttons** | 3 | 6mm x 6mm, through-hole | Amazon multipack, Omron B3F | $1.00 |
| **10kΩ Resistors** | 3 | Pull-up (optional, Pi has internal) | Any | $0.30 |

---

## 4. Wiring & Hardware (~$15)

| Component | Qty | Specifications | Recommended Sources | Est. Cost |
|-----------|:---:|----------------|---------------------|----------:|
| **Silicone Wire Kit** | 1 | 22 AWG, multi-color | Amazon | $8.00 |
| **2.54mm Header Pins** | 1 set | Male + Female | Amazon | $3.00 |
| **M2.5 Nylon Standoffs** | 1 kit | For Pi mounting | Amazon | $4.00 |
| **M3 Heat-Set Inserts** | 8 | Brass, 4mm length | Amazon, CNC Kitchen | $5.00 |
| **JST-PH Connectors** | 4 | 2-pin (optional, for clean wiring) | Adafruit, Amazon | $3.00 |

---

## 5. Acoustic Materials (~$15)

| Component | Qty | Specifications | Recommended Sources | Est. Cost |
|-----------|:---:|----------------|---------------------|----------:|
| **Acoustic Foam** | 1 sheet | 1" thick, self-adhesive | Amazon | $10.00 |
| **Silicone Gasket Sheet** | 1 | 2mm thick | Amazon | $5.00 |
| **Polyfill** | small bag | Polyester stuffing | Craft store | $3.00 |

---

## 6. 3D Printing Materials (~$10)

| Component | Qty | Specifications | Notes | Est. Cost |
|-----------|:---:|----------------|-------|----------:|
| **PETG Filament** | ~200g | Any color | Better vibration damping than PLA | $6.00 |
| **TPU Filament** | ~50g | For gaskets (optional) | Flexible seal material | $4.00 |

---

## Total Cost Summary

| Category | Cost |
|----------|-----:|
| Core Electronics | $45.10 |
| Voice Input (I2S mics) | $8-12 |
| Display & LEDs | $6.60 |
| Controls | $1.30 |
| Wiring & Hardware | $23.00 |
| Acoustic Materials | $18.00 |
| 3D Printing | $10.00 |
| **TOTAL** | **~$112-120** |

*Note: Speakers salvaged from original NS-CSPGASP unit (free)*

---

## Shopping Checklist

### Priority 1: Core (Order First)
- [ ] Raspberry Pi Zero 2 W
- [ ] MicroSD Card 32GB
- [ ] MAX98357A breakout x2
- [ ] INMP441 I2S MEMS microphones x2
- [ ] 5V 3A USB-C Power Supply

### Priority 2: Interface
- [ ] TM1637 4-digit display
- [ ] WS2812B RGB LEDs (3-5 pack)
- [ ] Tactile buttons (3+)
- [ ] USB-C breakout board

### Priority 3: Assembly
- [ ] Silicone wire kit
- [ ] Header pins
- [ ] M2.5 standoffs
- [ ] M3 heat-set inserts
- [ ] Acoustic foam
- [ ] Silicone sheet

### Priority 4: Filament
- [ ] PETG (~200g needed)

---

## Supplier Quick Links

| Supplier | Best For |
|----------|----------|
| [Adafruit](https://www.adafruit.com) | Pi, MAX98357A, quality breakouts |
| [SparkFun](https://www.sparkfun.com) | Alternatives to Adafruit |
| [Amazon](https://www.amazon.com) | Bulk components, wire, hardware |
| [AliExpress](https://www.aliexpress.com) | Budget TM1637, WS2812B, resistors |
| [DigiKey](https://www.digikey.com) | Precision components |

---

## Notes

1. **Pi Zero 2 W availability**: Can be scarce. Check [rpilocator.com](https://rpilocator.com) for stock alerts.

2. **MAX98357A quantity**: Buy 2 for stereo. Both receive the same I2S signal; channel selection is via SD_MODE pin.

3. **Heat-set inserts**: Require soldering iron with appropriate tip. Alternative: use self-tapping screws directly into PETG.

4. **Speaker reuse**: The original NS-CSPGASP speakers are 4Ω full-range drivers. Measure DC resistance to confirm (~3.2Ω expected).
