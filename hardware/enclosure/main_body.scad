/*
 * Open Hardware Smart Speaker Enclosure
 * Parametric design for NS-CSPGASP rebuild
 *
 * Form Factor: Landscape clock radio style
 * Features: Dual speaker chambers, display window, button holes
 */

// =============================================================================
// PARAMETERS - Adjust these based on your speaker measurements
// =============================================================================

// Speaker dimensions (measure your salvaged speakers!)
speaker_outer_diameter = 52;      // mm - mounting flange diameter
speaker_depth = 25;               // mm - front to deepest part of magnet
speaker_mounting_circle = 45;     // mm - diameter of mounting hole pattern
speaker_hole_diameter = 3;        // mm - mounting screw hole size
speaker_count = 4;                // number of mounting holes per speaker

// TM1637 display dimensions (standard 0.56" 4-digit module)
display_width = 42;               // mm
display_height = 24;              // mm
display_depth = 12;               // mm (PCB + components)

// Button dimensions (6mm tactile switch)
button_diameter = 6.5;            // mm - hole for button shaft
button_spacing = 15;              // mm - center to center

// WS2812B LED (single or small strip)
led_hole_diameter = 8;            // mm - diffuser hole

// INMP441 Microphone dimensions
mic_pcb_width = 14;               // mm - INMP441 module width
mic_pcb_length = 10;              // mm - INMP441 module length
mic_sound_port_diameter = 3;      // mm - sound port hole
mic_mounting_hole_diameter = 2;   // mm - for M2 screws
mic_spacing = 60;                 // mm - distance between mic centers (for beamforming)

// Enclosure parameters
wall_thickness = 4;               // mm - thicker for acoustic damping
internal_height = 70;             // mm - internal chamber height
front_panel_thickness = 3;        // mm

// Raspberry Pi Zero 2 W dimensions
pi_width = 65;                    // mm
pi_height = 30;                   // mm
pi_standoff_spacing_x = 58;       // mm
pi_standoff_spacing_y = 23;       // mm

// MAX98357A amplifier dimensions
amp_width = 25;                   // mm
amp_height = 20;                  // mm

// =============================================================================
// CALCULATED DIMENSIONS
// =============================================================================

// Speaker chamber sizing
speaker_chamber_width = speaker_outer_diameter + wall_thickness * 2 + 10;
speaker_chamber_depth = speaker_depth + 20;  // Extra for air volume

// Overall enclosure dimensions (landscape orientation)
enclosure_width = speaker_chamber_width * 2 + display_width + wall_thickness * 4;
enclosure_height = internal_height + wall_thickness * 2;
enclosure_depth = max(speaker_chamber_depth, 60) + wall_thickness * 2;  // Min 60mm for electronics

// Display position (centered)
display_x = enclosure_width / 2;
display_y = enclosure_height - 25;  // Near top

// Button positions (below display, centered)
button_y = display_y - display_height/2 - 20;

// =============================================================================
// MODULES
// =============================================================================

module speaker_cutout() {
    // Main speaker hole
    cylinder(h=wall_thickness*3, d=speaker_outer_diameter - 10, center=true, $fn=64);

    // Mounting holes
    for (i = [0:speaker_count-1]) {
        angle = i * (360 / speaker_count);
        translate([
            cos(angle) * speaker_mounting_circle/2,
            sin(angle) * speaker_mounting_circle/2,
            0
        ])
        cylinder(h=wall_thickness*3, d=speaker_hole_diameter, center=true, $fn=16);
    }
}

module speaker_grille() {
    // Decorative grille pattern
    grille_hole_size = 3;
    grille_spacing = 5;
    grille_radius = (speaker_outer_diameter - 15) / 2;

    for (x = [-grille_radius : grille_spacing : grille_radius]) {
        for (y = [-grille_radius : grille_spacing : grille_radius]) {
            if (sqrt(x*x + y*y) < grille_radius) {
                translate([x, y, 0])
                cylinder(h=wall_thickness*3, d=grille_hole_size, center=true, $fn=12);
            }
        }
    }
}

module display_cutout() {
    // Rectangular window for TM1637
    cube([display_width + 1, display_height + 1, wall_thickness*3], center=true);
}

module button_hole() {
    cylinder(h=wall_thickness*3, d=button_diameter, center=true, $fn=24);
}

module led_diffuser_hole() {
    cylinder(h=wall_thickness*3, d=led_hole_diameter, center=true, $fn=32);
}

module gasket_groove() {
    // Groove for speaker gasket (2mm wide, 1.5mm deep)
    difference() {
        cylinder(h=1.5, d=speaker_outer_diameter + 4, $fn=64);
        cylinder(h=3, d=speaker_outer_diameter, $fn=64);
    }
}

module pi_mounting_posts() {
    // M2.5 standoff posts for Pi Zero 2 W
    post_height = 8;
    post_outer_d = 6;
    post_inner_d = 2.5;

    for (x = [-pi_standoff_spacing_x/2, pi_standoff_spacing_x/2]) {
        for (y = [-pi_standoff_spacing_y/2, pi_standoff_spacing_y/2]) {
            translate([x, y, 0]) {
                difference() {
                    cylinder(h=post_height, d=post_outer_d, $fn=24);
                    cylinder(h=post_height+1, d=post_inner_d, $fn=16);
                }
            }
        }
    }
}

module amp_mounting_posts() {
    // Mounting posts for MAX98357A (2 posts)
    post_height = 6;
    post_outer_d = 5;
    post_inner_d = 2;
    spacing = 18;

    for (x = [-spacing/2, spacing/2]) {
        translate([x, 0, 0]) {
            difference() {
                cylinder(h=post_height, d=post_outer_d, $fn=24);
                cylinder(h=post_height+1, d=post_inner_d, $fn=16);
            }
        }
    }
}

module ventilation_slots() {
    // Thermal ventilation for Pi
    slot_width = 2;
    slot_length = 30;
    slot_spacing = 5;
    num_slots = 5;

    for (i = [0:num_slots-1]) {
        translate([0, i * slot_spacing - (num_slots-1)*slot_spacing/2, 0])
        cube([slot_length, slot_width, wall_thickness*3], center=true);
    }
}

module usb_c_cutout() {
    // USB-C port opening
    cube([10, 4, wall_thickness*3], center=true);
}

module heat_set_insert_hole() {
    // Hole for M3 heat-set insert (4mm dia, 5mm deep)
    cylinder(h=5, d=4, $fn=24);
}

module mic_sound_port() {
    // Sound port hole for INMP441 microphone
    cylinder(h=wall_thickness*3, d=mic_sound_port_diameter, center=true, $fn=24);
}

module mic_mounting_bracket() {
    // Internal bracket for mounting INMP441 microphone PCB
    // Positions mic 2-3mm below the top surface for acoustic coupling
    bracket_height = 3;
    bracket_width = mic_pcb_width + 4;
    bracket_length = mic_pcb_length + 4;
    standoff_height = 2;  // Gap between top surface and mic

    difference() {
        union() {
            // Base plate
            translate([0, 0, -bracket_height])
            cube([bracket_width, bracket_length, bracket_height], center=true);

            // Corner standoffs
            for (x = [-bracket_width/2 + 2, bracket_width/2 - 2]) {
                for (y = [-bracket_length/2 + 2, bracket_length/2 - 2]) {
                    translate([x, y, 0])
                    cylinder(h=standoff_height, d=4, $fn=16);
                }
            }
        }

        // Mounting holes for M2 screws
        for (x = [-bracket_width/2 + 2, bracket_width/2 - 2]) {
            for (y = [-bracket_length/2 + 2, bracket_length/2 - 2]) {
                translate([x, y, -bracket_height-1])
                cylinder(h=bracket_height + standoff_height + 2, d=mic_mounting_hole_diameter, $fn=16);
            }
        }

        // Sound hole passthrough (centered under mic's sound port)
        translate([0, 0, -bracket_height-1])
        cylinder(h=bracket_height + standoff_height + 2, d=mic_sound_port_diameter + 1, $fn=24);
    }
}

// =============================================================================
// MAIN ENCLOSURE
// =============================================================================

module main_body() {
    difference() {
        // Outer shell
        cube([enclosure_width, enclosure_height, enclosure_depth]);

        // Inner cavity
        translate([wall_thickness, wall_thickness, wall_thickness])
        cube([
            enclosure_width - wall_thickness*2,
            enclosure_height - wall_thickness*2,
            enclosure_depth - wall_thickness  // Open back
        ]);

        // Center divider cutout (separates L/R speaker chambers)
        // Actually we ADD this as a wall, so no cutout here

        // Speaker cutouts (front face)
        // Left speaker
        translate([speaker_chamber_width/2 + wall_thickness, enclosure_height/2, 0])
        rotate([0, 0, 0]) {
            speaker_cutout();
            translate([0, 0, wall_thickness/2])
            speaker_grille();
        }

        // Right speaker
        translate([enclosure_width - speaker_chamber_width/2 - wall_thickness, enclosure_height/2, 0])
        rotate([0, 0, 0]) {
            speaker_cutout();
            translate([0, 0, wall_thickness/2])
            speaker_grille();
        }

        // Display cutout (front face, centered)
        translate([display_x, display_y, 0])
        display_cutout();

        // Button holes (front face, below display)
        translate([display_x - button_spacing, button_y, 0])
        button_hole();  // Vol-

        translate([display_x, button_y, 0])
        button_hole();  // Mute

        translate([display_x + button_spacing, button_y, 0])
        button_hole();  // Vol+

        // LED diffuser hole (below buttons)
        translate([display_x, button_y - 15, 0])
        led_diffuser_hole();

        // Back panel ventilation
        translate([enclosure_width/2, enclosure_height/2, enclosure_depth])
        ventilation_slots();

        // USB-C power input (back, bottom center)
        translate([enclosure_width/2, 10, enclosure_depth])
        usb_c_cutout();

        // Microphone sound ports (top surface, centered, spaced for beamforming)
        // Left mic
        translate([enclosure_width/2 - mic_spacing/2, enclosure_height, enclosure_depth/3])
        rotate([90, 0, 0])
        mic_sound_port();

        // Right mic
        translate([enclosure_width/2 + mic_spacing/2, enclosure_height, enclosure_depth/3])
        rotate([90, 0, 0])
        mic_sound_port();
    }

    // Center divider wall (separates speaker chambers)
    translate([enclosure_width/2 - wall_thickness/2, wall_thickness, wall_thickness])
    cube([wall_thickness, enclosure_height - wall_thickness*2, enclosure_depth - wall_thickness - 20]);

    // Speaker gasket grooves (inside front face)
    translate([speaker_chamber_width/2 + wall_thickness, enclosure_height/2, wall_thickness])
    gasket_groove();

    translate([enclosure_width - speaker_chamber_width/2 - wall_thickness, enclosure_height/2, wall_thickness])
    gasket_groove();

    // Pi mounting posts (inside, bottom rear)
    translate([enclosure_width/2, 25, enclosure_depth - 30])
    rotate([90, 0, 0])
    pi_mounting_posts();

    // Amp mounting posts (inside, either side of Pi)
    translate([enclosure_width/2 - 35, 15, enclosure_depth - 20])
    rotate([90, 0, 0])
    amp_mounting_posts();

    translate([enclosure_width/2 + 35, 15, enclosure_depth - 20])
    rotate([90, 0, 0])
    amp_mounting_posts();

    // Microphone mounting brackets (inside, top surface)
    // Left mic bracket
    translate([enclosure_width/2 - mic_spacing/2, enclosure_height - wall_thickness, enclosure_depth/3])
    rotate([90, 0, 0])
    mic_mounting_bracket();

    // Right mic bracket
    translate([enclosure_width/2 + mic_spacing/2, enclosure_height - wall_thickness, enclosure_depth/3])
    rotate([90, 0, 0])
    mic_mounting_bracket();
}

module back_cover() {
    // Removable back panel
    cover_thickness = 3;

    difference() {
        cube([enclosure_width - 0.5, enclosure_height - 0.5, cover_thickness]);

        // Ventilation slots
        translate([enclosure_width/2, enclosure_height/2, 0])
        ventilation_slots();

        // USB-C cutout
        translate([enclosure_width/2, 10, 0])
        usb_c_cutout();

        // Screw holes for heat-set inserts
        translate([10, 10, 0]) cylinder(h=cover_thickness*3, d=3.2, $fn=16, center=true);
        translate([enclosure_width-10, 10, 0]) cylinder(h=cover_thickness*3, d=3.2, $fn=16, center=true);
        translate([10, enclosure_height-10, 0]) cylinder(h=cover_thickness*3, d=3.2, $fn=16, center=true);
        translate([enclosure_width-10, enclosure_height-10, 0]) cylinder(h=cover_thickness*3, d=3.2, $fn=16, center=true);
    }
}

// =============================================================================
// RENDER
// =============================================================================

// Uncomment one of these to render:

// Main enclosure body
main_body();

// Back cover (translate for printing separately)
// translate([0, enclosure_height + 10, 0]) back_cover();

// Show dimensions
echo("Enclosure dimensions:");
echo(str("  Width: ", enclosure_width, " mm"));
echo(str("  Height: ", enclosure_height, " mm"));
echo(str("  Depth: ", enclosure_depth, " mm"));
echo(str("  Speaker chamber width: ", speaker_chamber_width, " mm"));
