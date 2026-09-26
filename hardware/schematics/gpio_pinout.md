# GPIO Pinout Reference

**Raspberry Pi Zero 2 W GPIO Allocation**
**Project:** Open Hardware Smart Speaker

---

## Pin Assignment Table

| GPIO | Physical Pin | Function | Component | Wire Color (Suggested) |
|------|:------------:|----------|-----------|------------------------|
| **Power** |
| 5V | 2, 4 | Power Rail | Pi, Amps, Display | Red |
| 3.3V | 1, 17 | Logic Ref | (Reserved) | Orange |
| GND | 6, 9, 14, 20, 25, 30, 34, 39 | Ground | All | Black |
| **I2S Audio** |
| GPIO18 | 12 | BCLK | MAX98357A (both) | Blue |
| GPIO19 | 35 | LRCLK/FS | MAX98357A (both) | Green |
| GPIO21 | 40 | DOUT | MAX98357A (both) | Yellow |
| **TM1637 Display** |
| GPIO23 | 16 | CLK | TM1637 | Purple |
| GPIO24 | 18 | DIO | TM1637 | Gray |
| **WS2812B Status LED** |
| GPIO10 | 19 | DATA | WS2812B strip | White |
| **Volume LED** |
| GPIO12 | 32 | PWM | Single LED | Brown |
| **Buttons** |
| GPIO17 | 11 | VOL_UP | Tactile button | - |
| GPIO27 | 13 | VOL_DOWN | Tactile button | - |
| GPIO22 | 15 | MUTE | Tactile button | - |
| **I2S Microphone (Internal)** |
| GPIO18 | 12 | I2S_SCK | INMP441 (shared with amp BCLK) | Blue |
| GPIO19 | 35 | I2S_WS | INMP441 (shared with amp LRCLK) | Green |
| GPIO20 | 38 | I2S_DIN | INMP441 Data In | Orange |
| **Reserved for Future** |
| GPIO2 | 3 | SDA | I2C expansion | - |
| GPIO3 | 5 | SCL | I2C expansion | - |

---

## Visual Pinout (Pi Zero 2 W Header)

```
                    Pi Zero 2 W
                 (Component Side Up)

         3.3V [1]  [2] 5V ◄── Power In
    (I2C) SDA [3]  [4] 5V
    (I2C) SCL [5]  [6] GND
              [7]  [8]
          GND [9]  [10]
   VOL_UP ──► [11] [12] ◄── I2S BCLK
 VOL_DOWN ──► [13] [14] GND
    MUTE ──► [15] [16] ◄── TM1637 CLK
         3.3V [17] [18] ◄── TM1637 DIO
  WS2812B ──► [19] [20] GND
              [21] [22]
              [23] [24]
          GND [25] [26]
              [27] [28]
              [29] [30] GND
              [31] [32] ◄── Volume LED (PWM)
              [33] [34] GND
  I2S LRCLK ► [35] [36]
              [37] [38]
          GND [39] [40] ◄── I2S DOUT
```

---

## MAX98357A Wiring (Stereo Configuration)

Both amplifiers receive the **same I2S signals**. Channel selection is via SD_MODE pin.

### Left Channel Amp

| MAX98357A Pin | Connect To |
|---------------|------------|
| VIN | 5V Rail |
| GND | Ground |
| BCLK | GPIO18 (Pin 12) |
| LRC | GPIO19 (Pin 35) |
| DIN | GPIO21 (Pin 40) |
| GAIN | No connection (default 9dB) |
| SD_MODE | **Direct to VIN (5V)** |
| SPK+ | Left Speaker + |
| SPK- | Left Speaker - |

### Right Channel Amp

| MAX98357A Pin | Connect To |
|---------------|------------|
| VIN | 5V Rail |
| GND | Ground |
| BCLK | GPIO18 (Pin 12) |
| LRC | GPIO19 (Pin 35) |
| DIN | GPIO21 (Pin 40) |
| GAIN | No connection (default 9dB) |
| SD_MODE | **VIN via 390kΩ resistor** |
| SPK+ | Right Speaker + |
| SPK- | Right Speaker - |

### SD_MODE Channel Selection

| SD_MODE Connection | Output |
|--------------------|--------|
| GND | Shutdown (mute) |
| Direct to VIN | Left channel |
| VIN via 390kΩ | Right channel |
| No connection | Mono (L+R mix) |

---

## TM1637 Display Wiring

| TM1637 Pin | Connect To |
|------------|------------|
| CLK | GPIO23 (Pin 16) |
| DIO | GPIO24 (Pin 18) |
| VCC | 5V (or 3.3V) |
| GND | Ground |

*Note: TM1637 is 5V tolerant but works at 3.3V logic levels.*

---

## WS2812B RGB LED Wiring

| WS2812B Pin | Connect To |
|-------------|------------|
| DIN | GPIO10 (Pin 19) |
| VCC | 5V Rail |
| GND | Ground |

*Note: For long strips (>8 LEDs), add a 300-500Ω resistor on the data line and a 1000µF capacitor across power.*

---

## Button Wiring

Buttons connect GPIO to GND when pressed. Use internal pull-ups (enabled in software).

```
GPIO Pin ──┬── Button ──── GND
           │
         (Internal Pull-up enabled)
```

| Function | GPIO | Physical Pin |
|----------|------|:------------:|
| Volume Up | GPIO17 | 11 |
| Volume Down | GPIO27 | 13 |
| Mute | GPIO22 | 15 |

---

## Power Distribution

```
USB-C 5V Input (3A capable)
    │
    ├── Pi Zero 2 W (Pin 2 or 4) ─────── ~300mA typical
    │
    ├── MAX98357A #1 (VIN) ───────────── ~200mA @ load
    │
    ├── MAX98357A #2 (VIN) ───────────── ~200mA @ load
    │
    ├── TM1637 Display (VCC) ─────────── ~20mA
    │
    ├── WS2812B LEDs (VCC) ───────────── ~60mA per LED
    │
    └── Volume LED (via 220Ω) ────────── ~10mA

Total typical: ~800-900mA
Peak (loud audio): ~1.5A
```

**Important:** All grounds must be connected together (star ground at power input preferred).

---

## Microphone Options

### Option A: USB Microphone (Recommended)

Simply plug into the Pi Zero 2 W's USB port (via micro-USB OTG adapter).

**Recommended models:**
- PlayStation Eye camera (~$8) - 4-mic array
- ReSpeaker USB Mic Array v2.0 (~$25) - 4-mic array with LEDs
- Any USB conference microphone

**Pros:** Plug-and-play, no GPIO wiring, good echo cancellation with multi-mic arrays
**Cons:** Uses USB port, may need powered hub if also using other USB devices

### Option B: I2S MEMS Microphone (Advanced)

Uses INMP441 or SPH0645 I2S microphone modules.

| INMP441 Pin | Connect To |
|-------------|------------|
| VDD | 3.3V |
| GND | Ground |
| WS | GPIO19 (shared with amp LRCLK) |
| SCK | GPIO18 (shared with amp BCLK) |
| SD | GPIO20 (Pin 38) |
| L/R | GND (left channel) or 3.3V (right) |

**Pros:** Cleaner integration, no USB port used, lower latency
**Cons:** More complex wiring, requires I2S input configuration

**Note:** I2S input requires additional `/boot/config.txt` overlay:
```ini
dtoverlay=googlevoicehat-soundcard
# or use a custom overlay for simultaneous I2S in/out
```

---

## Software Configuration

### /boot/config.txt additions

```ini
# Disable onboard audio (uses I2S instead)
dtparam=audio=off

# Enable I2S output for MAX98357A
dtoverlay=hifiberry-dac
```

### GPIO Setup (Python)

```python
import RPi.GPIO as GPIO

# Button pins with internal pull-ups
GPIO.setmode(GPIO.BCM)
GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # VOL_UP
GPIO.setup(27, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # VOL_DOWN
GPIO.setup(22, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # MUTE

# Volume LED (PWM capable)
GPIO.setup(12, GPIO.OUT)
```
