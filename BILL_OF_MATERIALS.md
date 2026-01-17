# Bill of Materials: Insignia NS-CSPGASP Rebuild

**Objective:** Hardware shopping list for upgrading the Insignia Smart Speaker with a Raspberry Pi Zero 2 W.
**Status:** VALIDATED (All pinouts and dimensions confirmed).

## 1. Core Electronics (The "Brains")

| Component | qty | Specifications | Recommended SKUs | Est. Cost |
| :--- | :-: | :--- | :--- | :--- |
| **Controller** | 1 | **Raspberry Pi Zero 2 W**<br>*(Must be the "2 W" for quad-core power)* | • [Adafruit 5291](https://www.adafruit.com/product/5291)<br>• [The Pi Hut](https://thepihut.com/products/raspberry-pi-zero-2-w) | $15.00 |
| **Storage** | 1 | **MicroSD Card (16GB - 32GB)**<br>*(Class 10 / A1 rated)* | • SanDisk Ultra<br>• Samsung EVO Select | $6.00 |

## 2. Interface Hardware (The "Custom HAT")

| Component | qty | Specifications | Recommended SKUs | Est. Cost |
| :--- | :-: | :--- | :--- | :--- |
| **Proto HAT** | 1 | **Raspberry Pi Zero Proto HAT** (Shim)<br>*(Blank PCB to mount the breakout)* | • **Adafruit 3203** (Perma-Proto)<br>• **Pimoroni** Zero LiPo Shim (generic)<br>• [DigiKey/Mouser Alt] | $5.00 |
| **FPC Breakout** | 1 | **20-Pin 0.5mm** to DIP Adapter<br>*(Input: Mics + Touch + LED Pass-through)*<br>*(MUST have ZIF connector)* | • **Crystalfontz:** CFABB-CS050Z20G-A0<br>• **7Semi:** 20 Pin 0.5mm FFC Breakout<br>• **Tinkersphere:** 20 Pin 0.5mm FPC to DIP | $8-12 |
| **Extensions** | 1 | **FPC Extension Kit** (or Long Cables)<br>*(Essential for debugging)* | • **20-Pin 0.5mm Cable** (Main Link)<br>• **10-Pin 1.0mm Cable** (Inter-board Link) | $10.00 |
| **Audio Amp** | **2** | **MAX98357A** I2S Mono Amp<br>*(Buy TWO for Stereo - Confirmed Twin Amp topology)* | • **Adafruit 3006**<br>• **Amazon:** *"MAX98357A Breakout"* (Pack of 2) | $12.00 |
| **GPIO Header** | 1 | **2x20 Right-Angle Logic Header** (Male)<br>*(Required for 8mm Depth Limit)* | • **Adafruit:** 2x20 Right Angle Male Header<br>• **BC Robotics:** ACC-070<br>• **Amazon:** "2x20 Right Angle Header Male" | $2.00 |
| **Power Module** | 1 | **12V to 5V (3A) Buck Converter**<br>*(Essential if original brick is 12V)* | • **Pololu:** D24V50F5 (5V 5A)<br>• **Amazon:** "MP1584 Buck Converter"<br>• **Generic:** LM2596 Module (Bulky but works) | $3-5 |
| **Resistor** | 1 | **330kΩ - 470kΩ Resistor**<br>*(Required to set "Right Channel" on Amp 2)* | Any standard through-hole resistor. | $0.10 |

## 3. Wiring & Consumables

| Component | Description | Usage |
| :--- | :--- | :--- |
| **Ribbon Cable** | **20-Pin 0.5mm FFC** (Type A or B) | Keep the original! But buy a spare just in case ($2). |
| **Wire** | 24-26 AWG Silicone Wire | For wiring the HAT to the Pi GPIO. |
| **Power Cable** | **JST-PH 2-Pin** Pigtail (Female) | To splice into the internal speaker wire (optional but clean). |
| **Mounting** | Double-sided Foam Tape | To stick the Breakout Board to the Proto HAT. |

## 4. Tools Required
-   [ ] Soldering Iron & Solder
-   [ ] Flux (makes the job 10x easier)
-   [ ] Multimeter (for verifying the VCC voltage before first boot)
-   [ ] Wire Strippers

## Total Project Cost Estimate
**~ $45 - $55 USD** (Assuming you own the tools)

> [!TIP]
> **Don't Forget Headers!**
> If your Pi Zero 2 W *doesn't* come with pre-soldered GPIO headers, make sure to buy a **2x20 Male Header** strip (2.54mm) and solder it on!
