# Hardware Interface Guide (Insignia NS-CSPGASP)

## ⚠️ SAFETY WARNING ⚠️
-   **Voltage Logic Levels:** The "Condor" logic (SDA/SCL) is likely **3.3V**, but verify!
-   **Power Input:** The device power rail might be **5V** or **12V**. Check the label on the power brick and measure the internal "Red/Black" cable with a multimeter.
-   **Ribbon Cables:** These are fragile. Unlock connectors before pulling cables.

## 1. Top Board ("Condor Touch Board") & Front Display
The upper daughterboard contains the Capacitive Touch sensors. Crucially, **it also acts as a pass-through** for the signals going to the **Front LED Display** (visible in `IMG_2901.jpg`).

### Interface Topology
`Main Board` --(Ribbon Cable)--> `Top Board` --(Internal Routing)--> `Front LED Display` & `Microphones`

### Connection Point
-   **Target:** The Ribbon Cable (FPC) connector labeled **CN4**.
-   **Function:** Intercepting this *single cable* grants access to Touch, Display, and Microphones.
-   **Requirement:** A **Custom FPC Interface HAT**.
    -   Since no off-the-shelf HAT exists for this specific pinout, you must build one.
    -   **Parts:**
        1.  **Proto Zero HAT** (PCB that fits on Pi GPIO).
        2.  **20-Pin 0.5mm FPC Breakout Board**.
    -   **Assembly:** Solder the Breakout Board flat onto the Proto HAT and wire signals to GPIOs.
    -   **Pin Count:** **20 Pins** (Verified).
    -   **Pitch:** **0.5mm** (Verified).

### Pinout (Hypothetical - Requires Probing)
> [!IMPORTANT]
> **Safety First: Do NOT inject voltage yet!**
> The safest way to identify pins is to "Sniff" the original board while it is running.

### Pinout & Schematics
> [!IMPORTANT]
> **See `SCHEMATICS.md` for the precise ASCII Pinout Maps.**
> Use that document to verify every wire connection.

## 2. Component Analysis (Understanding the Hardware)

### The "Condor" Main Board
-   **Role:** Power management & Audio Amplification.
-   **Key Findings:**
    -   **Twin Mono Block:** The presence of **Two 4R7 Inductor pairs** + **Two LPS A6711 Chips** confirms a high-quality "Twin Mono" Stereo architecture.
    -   **Bypass Strategy:** We are completely removing the `S810BB` System-on-Module (the original "Brain") and replacing it with the Pi Zero 2 W.

### The Probing Strategy
**Goal:** Identify `VCC` (Power) and `GND` lines on the ribbon cable without frying anything.
1.  **Don't Probe the Pads:** The 0.5mm pads on the Top Board are too small.
2.  **Use the Breakout:** Plug the ribbon cable into your FPC Breakout Board. Probe the large DIP holes.
3.  **Trace GND:** Find the block of 4 contiguous pins. That is Ground.
4.  **Find VCC:** The pin measuring 3.3V or 5V relative to Ground is your power line.

## 3. Assembly Guide: "The Sandwich"
**Goal:** Create a single, solid unit that snaps onto the Pi.

### Step 1: Physical Mounting
1.  Stick the **FPC Breakout Board** to the center of the **Proto HAT** using foam tape.
2.  Solder short jumper wires from the Breakout pads to the nearest Proto HAT holes.

### Step 2: Input Module (Microphones & Controls)
*Refer to `SCHEMATICS.md` -> Section 2 for the FPC Pinout.*
-   **Connect:** `SDA`, `SCL`, `BCLK`, `LRC`, `DIN` (Mic Data), `GND`, `3.3V`.
-   **Note:** `BCLK` and `LRC` are shared buses. You will solder two wires to these pins (one from FPC, one going to Amps).

### Step 3: Output Module (Twin Stereo Amps)
*Refer to `SCHEMATICS.md` -> Section 3 for the Amp Wiring.*
**Logic:** We use the `SD_MODE` resistor method to separate Left/Right channels.

1.  **Amp 1 (Left):** Connect `SD_MODE` -> **5V** directly.
2.  **Amp 2 (Right):** Connect `SD_MODE` -> **5V** via **390kΩ Resistor**.
3.  **Wires:** Run 4 wires from the Pi (VSYS, GND, BCLK, LRC, DIN) to *both* amps (Daisy chain or Y-split).

### Step 4: Speaker Connection
**Do NOT connect speakers to the Pi.**
-   Trace the Red/Black wires from the **Left Speaker** -> Screw into **Amp 1**.
-   Trace the Red/Black wires from the **Right Speaker** -> Screw into **Amp 2**.

## 4. Power & Final Check
-   **Voltage Check:** Before plugging into the Pi, verify the Breakout Board `VCC` is getting 3.3V (Logic) and Amps are getting 5V (Power).
-   **Inductor Note:** The original board used a "Twin Mono Block" design (2 inductors per channel). By using two MAX98357A amps, we are faithfully restoring this high-quality topology.

