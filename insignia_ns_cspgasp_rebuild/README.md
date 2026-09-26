> **Archived.** This was the first plan: keep the Insignia case and drive its
> original display board from a Pi through an adapter for the ribbon cable. The
> main board turned out to be locked down, and splicing the ribbon bricked the
> unit. The project continues with new electronics and a new enclosure; see the
> [main README](../README.md). The bill of materials, the test bench for probing
> the ribbon (`BOM_POC_BENCH.md`), the mounting bracket and the probe scripts'
> `requirements.txt` from that plan are kept here for reference.

# Insignia NS-CSPGASP Rebuild (Condor Board Replacement)

This project documents the process of replacing the "brain" (Main Logic Board) of the **Insignia Voice Smart Bluetooth Speaker (NS-CSPGASP)** with a **Raspberry Pi Zero 2 W**.

## Why?
The original Google Assistant integration ("Condor" platform) often becomes unreliable or unsupported. This mod reuses the high-quality speaker, enclosure, and potentially the LED display to create a fully private, local-controlled smart speaker running:
-   Spotify Connect
-   Home Assistant (Voice Satellite)
-   AirPlay (via Shairport)

## Disclaimer
**This is an advanced hardware mod.**
-   Requires soldering.
-   Requires buying a Ribbon Cable Breakout board.
-   Involves working with power circuits.
-   **YOU DO THIS AT YOUR OWN RISK.**

## Current Status
-   [x] Teardown & Component Identification
-   [ ] Reverse Engineering Top Board (Display/Touch)
-   [ ] Designing FPC Interface
-   [ ] Final Assembly

See [HARDWARE.md](HARDWARE.md) for pinouts and wiring details.
