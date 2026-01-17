# PoC Test Bench: "Safe Sniffing" Setup

**Objective:** Safely characterize the signal pinout between the Main Board and Top Board without destroying the unit.

## 1. Required Components (The "Spread Out" Kit)
To access the signals while powered, you must extend the connection between the cemented Top Board and the Main Board.

| Component | Qty | Critical Spec | Search / SKU Examples | Why? |
| :--- | :--- | :--- | :--- | :--- |
| **FPC Extension Cable** | 1 | **20-Pin, 0.5mm Pitch** (Type A: Same Side) | • **Electrokit:** 41022543 (Type A)<br>• **Partsbaba:** PBFFC0344 (Type A)<br>• **Amazon:** "FFC Cable Type A Same Side" | **Crucial:** Type B (Reverse) will flip pin 1 to pin 20 and fry your board. Get Type A. |
| **FPC Coupler / Extender** | 1 | **20-Pin, 0.5mm Pitch** (Slide-Lock ZIF) | • **Adafruit:** 5203<br>• **DigiKey:** 1528-5203-ND<br>• **Sunrom:** 7631 | Joins the original short ribbon to your extension. |
| **Extension Jumper (Optional)** | 1 | **10-Pin, 1.0mm Pitch** | • **Amazon:** "10 pin 1.0mm FFC Cable" | For the LED Display if you want that active too. |
| **Logic Analyzer** | 1 | 8-Channel 24MHz | • **Amazon:** "HiLetgo 24MHz 8CH"<br>• **SparkFun:** TOL-18627 | **Essential** for decoding I2C data (display protocol). |

## 2. Bench Layout Map
This layout allows you to use the **Original Power Supply** while keeping the pin-dense ribbon cable exposed flat on your desk for probing.

```text
[ WALL ]
   ║
   (DC Jack)
   ║
[ CONDOR MAIN BOARD ]
   ║
   ║ (FPC Cable 1)
   ▼
[ BREAKOUT BOARD A ]  <-- (Input Side)
   ║
   ║  <-- JUMPER WIRES (The "Bridge") -->
   ║  * PROBE HERE! Attach clips to these wires.
   ║  * Signals flow through wires from Main to Top.
   ║
[ BREAKOUT BOARD B ]  <-- (Output Side)
   ║
   ║ (FPC Cable 2)
   ▼
[ CONDOR TOP BOARD ]
```

### 2.1 How the "Bridge" Works
1.  **Connection:** The signals flow from the **Main Board** -> **Cable 1** -> **Breakout A** -> **Jumper Wires** -> **Breakout B** -> **Cable 2** -> **Top Board**. The device acts exactly as if it were connected by a single cable.
2.  **Safety:** Instead of probing 0.5mm pads, you attach your probes to the **Jumper Wires** connecting the two boards.
    *   **Spacing:** Wires are spread out (2.54mm or more).
    *   **Grip:** Logic Analyzer hooks grab the wire insulation/metal securely.
    *   **No Shorts:** You can move wires apart to ensure they never touch.
3.  **Control:** You can unplug *one single wire* (e.g., disconnected the 3.3V line) to see what happens, without cutting any ribbon cables.

### 2.2 Safety Protocol: Preventing the Magic Smoke
**You are right to be paranoid. Wiring 20 jumpers creates 20 chances to swap a pin.**
Follow this procedure BEFORE plugging in the power brick:

1.  **Wire Methodically:** Connect Pin 1 to Pin 1. Pin 2 to Pin 2. Do not cross connect anything yet.
2.  **The "Beep" Test (Crucial):**
    *   Set Multimeter to *Continuity Mode* (Beep).
    *   Touch one probe to **Pin 1 Solder Pad** on Breakout A.
    *   Touch other probe to **Pin 1 Solder Pad** on Breakout B.
    *   **It MUST Beep.** (Continuity Confirmed).
    *   Repeat for Pin 20.
3.  **The "Short" Test:**
    *   Check continuity between **Pin 1** and **Pin 2**.
    *   **It MUST NOT Beep.** (No Shorts).
    *   Check continuity between **GND** (likely large planes) and **VCC** (if known).
4.  **Only then, Plug it in.**

### 2.3 Connecting the Logic Analyzer
The beauty of the Breadboard Bridge is that **rows are shared**.
1.  **GND First:** Connect the Logic Analyzer's `GND` wire to any wire you confirmed is Ground (Bridge Pin X).
2.  **Tap the Signal:**
    *   **Hole A:** Wire from Breakout 1 (Signal IN).
    *   **Hole B:** Wire to Breakout 2 (Signal OUT).
    *   **Hole C:** **Plug in your Logic Analyzer Channel 1 wire here.**
3.  Now the Analyzer "sees" the same voltage as the wire, without interrupting it.
4.  Repeat for Channels 2-8 to sniff multiple pins at once.

## 3. Diagnostic Tools
| Item | Spec | Search / SKU Examples | Why? |
| :--- | :--- | :--- | :--- |
| **Multimeter** | Voltmeter/Connectivity | Any Reliable Brand | Identifying 5V, 3.3V, and GND rails. |
| **Precision Needle Probes** | **< 1mm Tip** (Gold Plated) | • **Uxcell:** P50B (0.5mm Spear Tip)<br>• **Pace:** 1121-0680-P5<br>• **Amazon:** "0.5mm Multimeter Probe Spec" | **Essential.** Standard probes are too fat for 0.5mm pitch and will cause shorts. |
| **Logic Analyzer** | 24MHz 8-channel | **HiLetgo** / **KeeYees** (Generic 24MHz) | **HIGHLY RECOMMENDED.** Essential for decoding Display I2C. |

## 4. Workflows
1.  **Voltage Check:** Probe the generic pads on the Main Board first to confirm the 5V/12V rails.
2.  **Pinout Sniffing:**
    -   Connect Logic Analyzer connecting ground to a chassis shield.
    -   Tap channels 0-7 onto the FPC Extension wires.
    -   Capture signal traces during boot-up to identify `SDA`, `SCL`, `I2S` clocks.

## 5. Shopping List
Use this checklist to track your orders.

### Phase 1: Bench Essentials (For Sniffing)
*These items are required to probe the original board safely.*
- [x] **FPC Breakout Boards (The "Bridge")**
    - [x] [Amazon Search: "20 pin 0.5mm to DIP Adapter with Connector"](https://www.amazon.com/s?k=20+pin+0.5mm+to+dip+adapter+pcb+converter) - **BUY TWO (2)**.
    - **CRITICAL:** Ensure the board has the **FPC Connector PRE-SOLDERED**.
- [x] **FPC Extension Cables (20-pin 0.5mm)**
    - [x] [Adafruit #5203 (Coupler/Extender)](https://www.adafruit.com/product/5203) - *Buy 2*
    - [x] [Amazon Search: "20 pin 0.5mm ffc cable 200mm"](https://www.amazon.com/s?k=20+pin+0.5mm+ffc+cable+200mm) - *Get a multipack*
- [x] **Digital Multimeter (Fast Continuity)**
    - [x] [ANENG SZ06 (User Selected)](https://a.co/d/4sI5lbR) - *Confirmed: Has Audible Buzzer.*
- [x] **Logic Analyzer**
    - [x] [HiLetgo USB Logic Analyzer (Amazon)](https://www.amazon.com/dp/B077LSG5P2) - *Standard Clone*
- [x] **Extension Jumper (10-pin 1.0mm)**
    - [x] [Amazon Search: "10 pin 1.0mm pitch ffc cable"](https://www.amazon.com/s?k=10+pin+1.0mm+pitch+ffc+cable) - *Optional: For LED Display*

