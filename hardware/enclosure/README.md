# Enclosure 3D Printing Guide

## Files

| File | Description |
|------|-------------|
| `main_body.scad` | Parametric OpenSCAD source for main enclosure |
| `main_body.stl` | Export for printing (generate from SCAD) |
| `back_cover.stl` | Removable access panel |

## Before Printing

### 1. Measure Your Speakers

Update the parameters at the top of `main_body.scad` with your actual speaker measurements:

```openscad
speaker_outer_diameter = 52;      // mm - your measurement
speaker_depth = 25;               // mm - your measurement
speaker_mounting_circle = 45;     // mm - your measurement
```

See `../speaker_specs/measurements.md` for measurement guide.

### 2. Generate STL

Open `main_body.scad` in OpenSCAD and:
1. Press F5 to preview
2. Press F6 to render
3. Export as STL (File → Export → Export as STL)

For back cover, uncomment the `back_cover()` line and re-export.

---

## Print Settings

### Material: PETG (Recommended)

| Setting | Value | Notes |
|---------|-------|-------|
| **Material** | PETG | Better vibration damping than PLA |
| **Nozzle Temp** | 230-250°C | Per your filament |
| **Bed Temp** | 70-80°C | |
| **Layer Height** | 0.2mm | Balance of speed and quality |
| **Infill** | 40-60% | Higher = better acoustics |
| **Infill Pattern** | Gyroid or Grid | Gyroid is quieter |
| **Walls** | 3-4 perimeters | Stiffness matters |
| **Top/Bottom** | 4-5 layers | |
| **Supports** | Yes (touching buildplate) | For speaker grilles |

### Orientation

Print main body with **front face down** (speaker grilles on build plate):
- Better surface finish on visible front
- Supports only needed for internal features

### Estimated Print Time

- Main body: 8-14 hours (depending on size and infill)
- Back cover: 1-2 hours

### Filament Usage

- Main body: ~150-200g
- Back cover: ~30-50g

---

## Post-Processing

### 1. Remove Supports

Carefully remove support material from:
- Speaker grille holes
- Button holes
- Display window

### 2. Heat-Set Inserts

Install M3 brass heat-set inserts in the four corners for back panel attachment:
1. Heat soldering iron to ~220°C
2. Place insert on hole
3. Press straight down slowly
4. Let cool before handling

### 3. Test Fit Components

Before final assembly, test fit:
- [ ] Speakers sit flush in gasket grooves
- [ ] Display fits in window
- [ ] Buttons move freely in holes
- [ ] Pi mounts on standoffs
- [ ] Back cover attaches smoothly

---

## Acoustic Treatment

### Speaker Gaskets

Cut silicone gasket material to fit the gasket grooves:
1. Trace the groove diameter on silicone sheet
2. Cut outer circle
3. Cut inner circle (cone clearance)
4. Press into groove

### Internal Damping

Line the inside walls with acoustic foam:
- Speaker chambers: Full coverage
- Electronics bay: Partial (leave ventilation clear)

### Bass Tuning (Optional)

Add small amounts of polyfill to speaker chambers to tune low-frequency response. Start with a loose ball and adjust.

---

## Design Notes

### Chamber Separation

The center divider keeps left and right speaker chambers acoustically isolated. This prevents phase cancellation at low frequencies.

### Ventilation

The back panel has ventilation slots positioned over the Pi Zero. Ensure these remain unobstructed.

### Modularity

The back panel is removable for:
- Initial assembly
- Firmware updates (SD card access)
- Future modifications

---

## Customization

### Larger Speakers

If using larger speakers, increase:
- `speaker_outer_diameter`
- `speaker_chamber_width` (automatic)
- `internal_height` (if needed)

### Different Display

For different display modules, adjust:
- `display_width`
- `display_height`

### Add Aux Port

To add a 3.5mm audio jack, add a cutout in the back panel:
```openscad
// In back_cover() difference block:
translate([enclosure_width - 20, 10, 0])
cylinder(h=cover_thickness*3, d=6, $fn=24, center=true);
```

### USB Microphone Placement

The USB microphone connects via the Pi's micro-USB port. Options:

1. **External mic**: Route USB cable through a small hole in the back panel
2. **Internal mic**: Mount a small USB mic inside with sound ports in the front panel

For optimal voice pickup, position the microphone:
- Away from the speakers (reduces echo)
- Near the front of the enclosure
- With clear path to sound inlet holes

If using a ReSpeaker or similar array mic, you may want to mount it on top of the enclosure with its own bracket.
