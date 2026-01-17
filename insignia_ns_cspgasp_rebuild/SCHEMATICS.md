# System Schematics: Insignia NS-CSPGASP Rebuild

**Reference Document.** Use this for verifying pin locations and wire connections.

## 1. Raspberry Pi Zero 2 W (GPIO Header)
**View:** Top Down (Pins facing you).
**Orientation:** SD Card slot is LEFT. USB ports are BOTTOM.

```text
       [  5V ]  [  5V ]  (Pin 2/4 = Power for Amps)
         |        |
    +----v--------v----+
    |  o  o :: o  o  |  Pin 1 (3.3V) - Power for FPC Logic
    |  o  o :: o  o  |  Pin 3  (SDA) - FPC SDA
    |  o  o :: o  o  |  Pin 5  (SCL) - FPC SCL
    |  o  o :: o  o  |
    |  o  o :: o  o  |  Pin 9  (GND) - Common Ground
    |  o  o :: o  o  |
    |  o  o :: o  o  |
    |  o  o :: o  o  |
    |  o  o :: o  o  |
    |  o  o :: o  o  |  Pin 18 (BCLK)- SHARED: FPC + Amp 1 + Amp 2
    |  o  o :: o  o  |  Pin 20 (GND)
    |  o  o :: o  o  |  Pin 19 (LRC) - SHARED: FPC + Amp 1 + Amp 2
    |  o  o :: o  o  |  Pin 21 (DOUT)- Amp 1 + Amp 2 (Audio Out)
    +------------------+
          (USB Ports)
```

## 2. 20-Pin FPC Breakout Board (Input Module)
**View:** Top Down (Connector facing UP).
**Pitch:** 0.5mm
**Note:** Verify Pin 1 (Triangle) on your board.

```text
[   RIBBON CABLE ENTRY   ]
+------------------------+
| 1  2  3  4  5 ... 20   |
+--+--+--+--+--+---------+
   |  |  |  |  |
   |  |  |  |  +-- Pin 5 (GND) -> Pi GND
   |  |  |  +----- Pin 4 (RES) -> (Not Connected)
   |  |  +-------- Pin 3 (SDA) -> Pi Pin 3 (SDA)
   |  +----------- Pin 2 (SCL) -> Pi Pin 5 (SCL)
   +-------------- Pin 1 (INT) -> Pi GPIO 27 (Optional)

[ Crucial Signals ]
Pin 9  (BCK1)   -> Pi Pin 12 (GPIO 18 / BCLK) [*Shared*]
Pin 10 (FS1)    -> Pi Pin 35 (GPIO 19 / LRC)  [*Shared*]
Pin 11 (MIC_SD) -> Pi Pin 38 (GPIO 20 / DIN)  [Mic Data In]
Pin 20 (VCC)    -> Pi 3.3V / 5V (Verify Voltage!)
```

## 3. Stereo Amplifier Module (MAX98357A Pair)
**View:** Top Down (Chip up).

**Left Channel Amp (Amp 1)**
```text
      [ VIN ] <--- 5V (Pi Pin 2/4)
      [ GND ] <--- GND
      [ DIN ] <--- Pi Pin 40 (GPIO 21 / DOUT)
      [BCLK ] <--- Pi Pin 12 (GPIO 18 / BCLK)
      [ LRC ] <--- Pi Pin 35 (GPIO 19 / LRC)
      [ GAIN]      (Float = 9dB default)
      [ SD  ] <=== WIRE ===> [ VIN / 5V ]  (Threshold > 1.4V = LEFT)
```

**Right Channel Amp (Amp 2)**
```text
      [ VIN ] <--- 5V (Pi Pin 2/4)
      [ GND ] <--- GND
      [ DIN ] <--- Pi Pin 40 (GPIO 21 / DOUT)
      [BCLK ] <--- Pi Pin 12 (GPIO 18 / BCLK)
      [ LRC ] <--- Pi Pin 35 (GPIO 19 / LRC)
      [ GAIN]      (Float = 9dB default)
## 4. Internal Connections (Reference Only)
**Front LED Display (10-Pin 1.0mm)**
*This cable connects the Top Board (Daughter) to the Front Face.*
-   **Connection:** Logic is handled by the Top Board.
-   **Control:** The Pi controls this indirectly via the main **20-Pin FPC** (likely `SDA`/`SCL`).
-   **Debugging:** You may need the **10-Pin Extension Cable** to keep this connected while the Top Board is removed for testing.

## 5. Power Distribution Map (Star Topology)

**WARNING:** Do NOT power the system via the Pi's Micro-USB port alone. The Amps + Display + Pi will exceed the current limit. Use a dedicated 5V rail.

### 5.1 The Logic
Instead of daisy-chaining, we use a **Star Topology** where all high-current devices connect directly to the main 5V source.

```
[DC Input Jack] (12V or 5V)
      │
      ▼
[Buck Converter] (Step-Down Regulator)
   Input: 12V (or 5V if bypassing)
   Output: 5.0V (Adjusted to precise 5.1V is ideal)
      │
      ▼
[Terminals / Shared 5V Rail] ════════════════════════╗
      │                    │                    │    │
      ▼                    ▼                    ▼    ▼
[Pi Zero 2 W]        [Amp 1 Left]         [Amp 2 Right]
   (Pin 2/4)            (VIN)                (VIN)
      │                    │                    │
      ▼                    ▼                    ▼
   [GND Rail] ═══════════════════════════════════════╝
```

### 5.2 Wiring Guide (5V Source)
| Component | Wire Color | Connect To |
| :--- | :--- | :--- |
| **Pi Zero 2 W** | Red | **Pin 2 (5V)** *Directly* |
| | Black | **Pin 6 (GND)** |
| **MAX98357A (Left)** | Red | **Shared 5V Rail** |
| | Black | **Shared GND Rail** |
| **MAX98357A (Right)** | Red | **Shared 5V Rail** |
| | Black | **Shared GND Rail** |
| **Top Board** | TBD | **Shared 5V Rail** (Verify First!) |

