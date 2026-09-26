# Speaker Measurements

**Source:** Insignia NS-CSPGASP (salvaged)
**Date:** _____________
**Measured By:** _____________

---

## Speaker Identification

| Property | Left Speaker | Right Speaker |
|----------|--------------|---------------|
| Markings/Part# | | |
| Manufacturer | | |

---

## Physical Dimensions

### Outer Diameter (Mounting Flange)

```
        ┌─────────────────┐
        │    ◄─────────►  │
        │     Diameter    │
        │                 │
        │    (Speaker)    │
        │                 │
        └─────────────────┘
```

| Measurement | Left Speaker | Right Speaker |
|-------------|--------------|---------------|
| Outer Diameter | ______ mm | ______ mm |
| Cone Diameter (visible) | ______ mm | ______ mm |

### Depth (Front to Back)

```
    Front ──┬────────────────┬── Back
            │                │
            │◄── Depth ────►│
            │                │
            ├────────────────┤
            │    (Magnet)    │
            └────────────────┘
```

| Measurement | Left Speaker | Right Speaker |
|-------------|--------------|---------------|
| Total Depth | ______ mm | ______ mm |
| Magnet Depth | ______ mm | ______ mm |

### Mounting Holes

```
           ┌───●───────●───┐
           │               │
           │   (Speaker)   │
           │               │
           └───●───────●───┘
               ◄───────►
              Hole Spacing
```

| Measurement | Left Speaker | Right Speaker |
|-------------|--------------|---------------|
| # of Mounting Holes | | |
| Hole Diameter | ______ mm | ______ mm |
| Hole Pattern (circle dia.) | ______ mm | ______ mm |
| Screw Size (if known) | M____ | M____ |

---

## Electrical Measurements

### DC Resistance (DCR)

**Method:** Set multimeter to Ω (resistance). Touch probes to speaker terminals.

| Measurement | Left Speaker | Right Speaker |
|-------------|--------------|---------------|
| DC Resistance | ______ Ω | ______ Ω |

*Expected: ~3.0-3.5Ω for a 4Ω speaker, ~6-7Ω for an 8Ω speaker*

### Polarity Check

Mark the positive terminal! When a 1.5V battery is briefly touched:
- **Positive to +**: Cone moves **outward**
- **Positive to -**: Cone moves **inward**

| Speaker | + Terminal Identified | Wire Color (if any) |
|---------|----------------------|---------------------|
| Left | [ ] Yes | |
| Right | [ ] Yes | |

---

## Calculated/Estimated Specifications

Based on measurements and typical small speaker characteristics:

| Specification | Estimated Value | Notes |
|---------------|-----------------|-------|
| Nominal Impedance | 4Ω / 8Ω (circle) | Based on DCR |
| Power Handling | ~3-5W | Typical for this size |
| Frequency Range | ~200Hz - 15kHz | Estimate for 2" driver |

---

## Photos

Attach or link photos of the speakers with ruler for scale:

- [ ] Front view with ruler
- [ ] Side view (depth)
- [ ] Back view (magnet/terminals)
- [ ] Mounting hole detail

Photo locations:
```
ref-images/speaker_front.jpg
ref-images/speaker_side.jpg
ref-images/speaker_back.jpg
```

---

## Enclosure Design Parameters

**Copy these values to the OpenSCAD file:**

```openscad
// Speaker parameters from measurements
speaker_outer_diameter = ______;  // mm
speaker_depth = ______;           // mm
speaker_mounting_holes = ______;  // mm (circle diameter)
speaker_hole_diameter = ______;   // mm
speaker_impedance = ______;       // ohms (4 or 8)
```

---

## Notes

_Any observations about speaker condition, wire lengths, connector types, etc._

```




```

---

## Comparison to Estimated Values

From reference photos, the speakers appeared to be approximately 52mm diameter. Compare your measurements:

| Parameter | Estimated (from photos) | Actual Measured |
|-----------|------------------------|-----------------|
| Outer Diameter | ~52mm | ______ mm |
| Depth | ~20-25mm | ______ mm |
| Impedance | 4Ω | ______ Ω |
