# Assembly Guide: Open Hardware Smart Speaker

Step-by-step instructions for building the open hardware smart speaker from salvaged NS-CSPGASP speakers and new components.

---

## Prerequisites

### Tools Required

- [ ] Soldering iron (temperature controlled, ~350°C)
- [ ] Solder (60/40 or lead-free)
- [ ] Flux (makes soldering easier)
- [ ] Wire strippers
- [ ] Multimeter
- [ ] Small screwdrivers (Phillips, flathead)
- [ ] Heat gun or lighter (for heat-shrink)
- [ ] 3D printer (or access to one)
- [ ] Hot glue gun (optional)

### Components

See [docs/BOM.md](BOM.md) for the full bill of materials.

**Minimum required:**
- Raspberry Pi Zero 2 W
- 32GB MicroSD card
- 2x MAX98357A I2S amplifiers
- USB Microphone (for voice control)
- TM1637 4-digit display
- 3x WS2812B RGB LEDs
- 3x tactile buttons
- 5V 3A USB-C power supply
- Micro-USB OTG adapter (for USB mic)
- Salvaged speakers from NS-CSPGASP
- 3D printed enclosure

---

## Phase 1: Speaker Extraction

### 1.1 Open the NS-CSPGASP

1. Flip the unit upside down
2. Remove any visible screws (check under rubber feet)
3. Use a plastic pry tool to release clips around the seam
4. Carefully separate the enclosure halves

### 1.2 Remove the Speakers

1. Locate both speakers (left and right sides)
2. Note the wire colors and polarity (+ and -)
3. Disconnect or cut speaker wires from the original board
4. Remove mounting screws
5. Gently lift speakers out

### 1.3 Measure and Document

Fill out [hardware/speaker_specs/measurements.md](../hardware/speaker_specs/measurements.md):

1. **Outer diameter**: Measure the mounting flange
2. **Depth**: Measure from front to back of magnet
3. **Mounting holes**: Count and measure hole positions
4. **DC Resistance**: Set multimeter to Ω, measure across terminals

**Expected values:**
- Diameter: ~52mm
- Depth: ~20-25mm
- Impedance: ~3.2Ω DC resistance (4Ω nominal)

### 1.4 Test Speakers

Before proceeding, verify speakers work:

1. Connect to any audio source briefly
2. Play a test tone
3. Listen for distortion or rattling

---

## Phase 2: Raspberry Pi Setup

### 2.1 Flash the OS

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Select "Raspberry Pi OS Lite (64-bit)"
3. Click the gear icon for advanced options:
   - Set hostname: `open-speaker`
   - Enable SSH
   - Set username/password
   - Configure WiFi
4. Flash to SD card

### 2.2 First Boot Configuration

1. Insert SD card into Pi Zero 2 W
2. Power on (initial boot takes ~2 minutes)
3. SSH in: `ssh pi@open-speaker.local`

### 2.3 Audio Configuration

Edit `/boot/config.txt`:
```bash
sudo nano /boot/config.txt
```

Add these lines:
```ini
dtparam=audio=off
dtoverlay=hifiberry-dac
```

Reboot:
```bash
sudo reboot
```

### 2.4 Install Dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install audio tools
sudo apt install -y alsa-utils

# Install Python dependencies
sudo apt install -y python3-pip python3-dev

# Install GPIO and LED libraries
sudo pip3 install RPi.GPIO adafruit-circuitpython-neopixel rpi_ws281x
```

---

## Phase 3: Audio Path Testing

### 3.1 Wire First Amplifier

Connect MAX98357A #1 to Pi (use breadboard for testing):

| MAX98357A | Pi Zero 2 W |
|-----------|-------------|
| VIN | 5V (Pin 2) |
| GND | GND (Pin 6) |
| BCLK | GPIO18 (Pin 12) |
| LRC | GPIO19 (Pin 35) |
| DIN | GPIO21 (Pin 40) |
| SD_MODE | VIN (direct) |

Connect a speaker to SPK+ and SPK-.

### 3.2 Test Audio

```bash
# List audio devices
aplay -l

# Play test tone
speaker-test -c 1 -t sine -f 440

# If no sound, check:
# - config.txt has the overlay
# - Wiring is correct
# - Volume: alsamixer
```

### 3.3 Add Second Amplifier (Stereo)

Wire MAX98357A #2 identically EXCEPT:
- **SD_MODE**: Connect to VIN through a **390kΩ resistor**

This selects the right channel.

### 3.4 Test Stereo

```bash
# Play stereo test (alternates left/right)
speaker-test -c 2 -t sine
```

---

## Phase 4: Microphone Setup (I2S MEMS)

This project uses internal I2S MEMS microphones for a clean, integrated design matching professional voice assistants.

### 4.1 Wire INMP441 Microphones

Wire both INMP441 modules to share the I2S clock signals with the amplifiers:

| INMP441 Pin | Connect To | Notes |
|-------------|------------|-------|
| VDD | 3.3V (Pin 1) | **NOT 5V** - INMP441 is 3.3V only |
| GND | GND (Pin 9) | |
| WS | GPIO19 (Pin 35) | Shared with amp LRCLK |
| SCK | GPIO18 (Pin 12) | Shared with amp BCLK |
| SD | GPIO20 (Pin 38) | Microphone data output |
| L/R | See below | Channel selection |

**Channel selection for dual-mic setup:**
- Mic #1: L/R pin → GND (left channel)
- Mic #2: L/R pin → 3.3V (right channel)

### 4.2 Physical Mounting

Mount microphones on **top of enclosure** for optimal voice pickup:

1. Drill 2-3mm sound ports in top panel (or use pre-designed holes)
2. Cover ports with fine mesh to block dust
3. Mount mic PCB 2-3mm below sound port
4. Add acoustic isolation gasket between mic PCB and enclosure
5. Keep mic wiring away from power lines (reduces noise)

**Positioning:**
```
         [Top View of Enclosure]
    +--------------------------------+
    |    (mic L)          (mic R)    |
    |       ○                ○       |  ← Sound ports
    |                                |
    |   [======DISPLAY======]        |
    |                                |
    +--------------------------------+
```

### 4.3 Configure I2S Input

Edit `/boot/config.txt`:
```bash
sudo nano /boot/config.txt
```

Add the I2S microphone overlay:
```ini
# I2S microphone input (in addition to hifiberry-dac for output)
dtoverlay=googlevoicehat-soundcard
```

*Note: The googlevoicehat-soundcard overlay supports simultaneous I2S input and output. For custom configurations, you may need a different overlay.*

Reboot:
```bash
sudo reboot
```

### 4.4 Verify Microphone Detection

```bash
# List recording devices
arecord -l

# Should show something like:
# card 0: sndrpigooglevoi [snd_rpi_googlevoicehat_soundcar], device 0: Google voiceHAT SoundCard ...
```

### 4.5 Test Recording

```bash
# Record 5 seconds of audio (adjust hw:X,0 based on arecord -l output)
arecord -D hw:0,0 -c 2 -r 48000 -f S32_LE -d 5 test.wav

# Play it back
aplay test.wav

# Clean up
rm test.wav
```

### 4.6 Configure Default Audio Devices

Create/edit `~/.asoundrc`:
```bash
nano ~/.asoundrc
```

Add:
```
pcm.!default {
    type asym
    playback.pcm "plughw:0,0"
    capture.pcm "plughw:0,0"
}
```

*Note: With googlevoicehat-soundcard, both playback and capture may be on the same card.*

### 4.7 Troubleshooting I2S Microphones

**No sound captured:**
1. Check WS and SCK connections (must be shared with amplifiers)
2. Verify SD pin is connected to GPIO20
3. Check 3.3V power (NOT 5V)
4. Verify overlay is loaded: `dmesg | grep -i i2s`

**Only one channel working:**
1. Check L/R pin connections (GND vs 3.3V)
2. Both mics need different L/R settings

**Noise/interference:**
1. Route mic wires away from speaker/power wires
2. Use shielded wire if needed
3. Add ferrite bead on mic power line

---

## Phase 5: Display and Controls

### 5.1 Wire TM1637 Display

| TM1637 | Pi Zero 2 W |
|--------|-------------|
| VCC | 3.3V (Pin 1) or 5V |
| GND | GND (Pin 9) |
| CLK | GPIO23 (Pin 16) |
| DIO | GPIO24 (Pin 18) |

### 5.2 Test Display

```bash
cd /home/pi/open-speaker/firmware
python3 display/tm1637_driver.py
```

Should show test patterns and time.

### 5.3 Wire WS2812B LEDs

| WS2812B | Pi Zero 2 W |
|---------|-------------|
| VCC | 5V (Pin 4) |
| GND | GND (Pin 14) |
| DIN | GPIO10 (Pin 19) |

If using multiple LEDs, daisy-chain DOUT → DIN.

### 5.4 Test LEDs

```bash
# May need sudo for PWM access
sudo python3 display/ws2812_status.py
```

Should cycle through colors.

### 5.5 Wire Buttons

Each button connects between GPIO and GND:

| Button | GPIO | Pin |
|--------|------|-----|
| VOL_UP | GPIO17 | 11 |
| VOL_DOWN | GPIO27 | 13 |
| MUTE | GPIO22 | 15 |

Internal pull-ups are enabled in software.

### 5.6 Test Buttons

```bash
python3 controls/button_handler.py
```

Press buttons and verify detection.

---

## Phase 6: Enclosure Preparation

### 6.1 Update OpenSCAD Parameters

Edit `hardware/enclosure/main_body.scad`:

```openscad
speaker_outer_diameter = XX;  // Your measurement
speaker_depth = XX;           // Your measurement
speaker_mounting_circle = XX; // Your measurement
```

### 6.2 Generate STL

1. Open in OpenSCAD
2. Press F6 to render
3. Export as STL

### 6.3 Print Enclosure

**Recommended settings:**
- Material: PETG
- Layer height: 0.2mm
- Infill: 50%
- Walls: 4 perimeters

**Print order:**
1. Main body (~10 hours)
2. Back cover (~2 hours)

### 6.4 Post-Processing

1. Remove supports
2. Install M3 heat-set inserts (soldering iron at 220°C)
3. Test fit all components

---

## Phase 7: Final Assembly

### 7.1 Prepare Wiring

Cut wires to appropriate lengths:
- Power wires: 10cm
- I2S wires: 8cm
- Button wires: 15cm (for routing)

Use different colors per the [GPIO pinout](../hardware/schematics/gpio_pinout.md).

### 7.2 Solder Connections

1. **Pi header**: Solder 2x20 header if not pre-installed
2. **Amplifiers**: Solder pin headers or direct wires
3. **Display**: Solder pin headers or direct wires
4. **Buttons**: Solder wires with heat-shrink

### 7.3 Mount Electronics

1. Attach Pi Zero to standoffs in enclosure
2. Mount amplifiers near speakers
3. Mount display in front panel cutout
4. Install buttons in front panel holes
5. Install RGB LEDs

### 7.4 Install Speakers

1. Cut silicone gasket to fit groove
2. Place gasket in groove
3. Position speaker
4. Secure with screws
5. Connect speaker wires to amplifiers

### 7.5 Acoustic Treatment

1. Line speaker chambers with acoustic foam
2. Add polyfill loosely (don't overpack)
3. Ensure no foam blocks ventilation

### 7.6 Close Enclosure

1. Route all wires neatly
2. Verify no pinched wires
3. Attach back cover with M3 screws

---

## Phase 8: Software Installation

### 8.1 Copy Firmware

```bash
# On your PC, SCP the firmware folder
scp -r firmware/ pi@open-speaker.local:/home/pi/open-speaker/
```

### 8.2 Install Service

```bash
# On the Pi
sudo cp /home/pi/open-speaker/config/systemd/open-speaker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable open-speaker
sudo systemctl start open-speaker
```

### 8.3 Verify Operation

```bash
# Check service status
sudo systemctl status open-speaker

# View logs
journalctl -u open-speaker -f
```

---

## Troubleshooting

### No Audio

1. Check `aplay -l` shows the I2S device
2. Verify `/boot/config.txt` settings
3. Check wiring (especially BCLK, LRC, DIN)
4. Try: `alsamixer` to unmute/raise volume

### Display Not Working

1. Check CLK and DIO wiring
2. Try swapping CLK/DIO (easy to mix up)
3. Test with different brightness levels

### LEDs Not Working

1. Must run as `sudo` (PWM requires root)
2. Check data pin connection
3. Verify 5V power to LEDs

### Buttons Not Responding

1. Check GPIO numbers match code
2. Verify buttons connect GPIO to GND
3. Test with multimeter (continuity when pressed)

---

## Next Steps

After basic assembly:

1. **Spotify Connect**: Install `spotifyd`
2. **Voice Control**: Add USB microphone and Wyoming Satellite
3. **Home Assistant**: Configure integration
4. **Custom Wake Word**: Train with Porcupine

See the main [README](../README.md) for advanced configuration.
