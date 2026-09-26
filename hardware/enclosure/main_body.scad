/*
 * Open Speaker enclosure: NS-CSPGASP open-hardware rebuild
 *
 * A tall tower on roughly the original's footprint (the smaller, mains-powered
 * Insignia NS-CSPGASP is 96 x 96 x 151.6 mm):
 *   - lower section: bass chamber with the two salvaged drivers firing left and
 *     right behind round grilles, plus a tuned port (or passive radiator, or sealed)
 *   - a groove around the waist; the status light glows through it at the front
 *   - upper section: electronics bay with the clock display behind a smoked window
 *   - top plate: three buttons and two microphones, no visible fasteners
 *   - back panel: the only screwed part; it carries the port, USB-C power, the
 *     microphone mute button, and locks the top plate in place
 *
 * Every part prints in PETG without supports; orientations are in README.md.
 * OpenSCAD 2021.01 or newer. Pick a part with -D 'part="body"' etc.
 *
 * DRIVER DIMENSIONS ARE ESTIMATES until you fill in
 * hardware/speaker_specs/measurements.md; measure and edit the values below.
 */

/* [Part] */
// assembly | exploded | section | section_front | print_layout | body | deck | top_plate | back_panel | grille | clamp_ring | caps | diffuser | window | port_plug
part = "assembly";
// render colours only: light | dark
colorway = "light";

/* [Overall] */
enclosure_width = 100;      // X, left to right (NS-CSPGASP: 96)
enclosure_depth = 100;      // Y, front to back (NS-CSPGASP: 96)
enclosure_height = 160;     // Z (NS-CSPGASP: 151.6)
corner_radius = 10;
top_chamfer = 2;
bottom_chamfer = 1.5;
wall_thickness = 4;
back_thickness = 4;         // back panel
top_thickness = 3;          // top plate
waist_z = 92;               // groove around the body; the status light shines through it at the front

/* [Speakers: estimates, measure yours] */
speaker_frame_diameter = 52;    // outside of the frame / mounting flange
speaker_cone_diameter = 46;     // cone + surround; the clamp ring must not cover it
speaker_basket_diameter = 46;   // widest part behind the flange (passes through the wall)
speaker_flange_thickness = 3;
speaker_depth = 25;             // front of the flange to the back of the magnet
speaker_magnet_diameter = 30;
speaker_center_y = 50;          // from the front
speaker_center_z = 46;
// clamp: a printed ring holds the frame (works for any round driver)
// holes: screws through the frame's own holes
speaker_mount = "clamp";
speaker_hole_circle = 45;       // holes mode only
speaker_hole_count = 4;
speaker_hole_angle = 45;

/* [Grilles] */
grille_pattern = "hex";         // hex | rings
grille_thickness = 1.5;

/* [Bass] */
bass_mode = "port";             // port | passive_radiator | sealed
deck_z = 84;                    // top of the chamber
deck_thickness = 3;
port_diameter = 16;
port_wall = 2;
port_tuning_hz = 120;
radiator_frame = 55;            // passive radiator (measure yours)
radiator_cutout = 49;
radiator_hole_circle = 60;
radiator_hole_count = 4;

/* [Display] */
display_type = "oled_1_3";      // oled_1_3 | oled_2_42 | tm1637
display_center_z = 125;         // centre of the visible area
window_thickness = 2;           // smoked acrylic window, flush with the front

/* [Status light] */
light_length = 44;
light_height = 2.4;

/* [Controls] */
button_diameter = 10;
button_pitch = 17.78;           // 7 x 2.54 mm: all three switches fit one strip of perfboard
button_y = 50;                  // row of buttons and microphones, from the front
switch_height = 5;              // 6 x 6 mm tactile switch: board to top of the plunger
cap_proud = 0.8;                // how far the caps stand above the surface
mute_x = 50;                    // microphone mute button on the back panel
mute_z = 146;

/* [Microphones] */
mic_pcb = 14;                   // INMP441 breakout, 14 x 14 mm
mic_port_diameter = 1.6;
mic_spacing = 68;

/* [Electronics] */
pi_origin = [18.5, 26];         // Pi Zero 2 W corner (x, y) on the deck; microSD end faces the back
standoff_height = 5;
amp_board = [19.4, 17.8];       // Adafruit 3006 MAX98357A
usbc_board = [14.2, 20.4, 1.6]; // Adafruit 4090: across, along the plug, PCB thickness
usbc_x = 68;
usbc_z = 101;                   // centre of the receptacle

/* [Fit and fasteners] */
fit = 0.25;                     // clearance between printed parts
seal = 0.5;                     // compressed foam tape wherever the chamber must be airtight
insert_diameter = 4.0;          // M3 heat-set insert
insert_depth = 6;
m3_clearance = 3.4;
m3_head = 6.2;                  // countersunk
m3_pilot = 2.6;                 // M3 screw cutting its own thread in PETG
m25_pilot = 2.2;
m2_pilot = 1.7;

/* [Rendering] */
$fn = 64;

// ---------------------------------------------------------------------------
// Derived values

W = enclosure_width;
D = enclosure_depth;
H = enclosure_height;
r = corner_radius;
w = wall_thickness;
bt = back_thickness;
tt = top_thickness;
eps = 0.01;

frame = 8;                          // how far the back panel overlaps the body
frame_t = 3;                        // body frame around the back opening
panel_x0 = r;                       // the back panel fills the flat part of the back
panel_x1 = W - r;
open_x0 = panel_x0 + frame;         // access opening
open_x1 = panel_x1 - frame;
open_z0 = w + frame;
panel_y = D - bt;                   // inside face of the back panel
inner_back = panel_y - frame_t;     // the cavity ends here beside the opening
deck_top = deck_z + deck_thickness;
plate_z = H - tt;                   // underside of the top plate

// drivers: stack from the outside face inwards
clamp = speaker_mount == "clamp";
ring_t = 2.4;
ring_od = speaker_frame_diameter + 18;
ring_screw_circle = speaker_frame_diameter + 10;
grille_d = clamp ? ring_od : max(speaker_frame_diameter, speaker_hole_circle + 7) + 6;
grille_recess = grille_thickness + 0.3;                         // grilles sit 0.3 mm below the surface
flange_front = grille_recess + (clamp ? ring_t : 2.5);          // holes mode: room for pan heads
seat_floor = flange_front + speaker_flange_thickness + seal;
boss_depth = (clamp ? flange_front : seat_floor) + 9;           // M3 x 8 screws
boss_r = grille_d/2 + fit + 2.5;

// display presets:
// [pcb_w, pcb_h, pcb_t, face_w, face_h, face_t, active_w, active_h, active_dy, window_w, window_h]
display = display_type == "oled_2_42" ? [70.9, 43.4, 1.6, 60.5, 37.0, 2.0, 55.01, 27.49, 0, 68, 40] :
          display_type == "tm1637"    ? [42.0, 24.0, 1.6, 30.0, 14.0, 7.0, 30.0, 14.0, 0, 44, 24] :
                                        [35.4, 33.5, 1.6, 34.5, 23.0, 1.1, 29.42, 14.70, 0, 52, 30];
pcb_w = display[0];
pcb_h = display[1];
pcb_t = display[2];
face_t = display[5];
active = [display[6], display[7]];
pcb_cz = display_center_z - display[8];
window = [display[9], display[10]];

cap_flange = 1.2;
cap_flange_d = button_diameter + 2.4;
switch_boss_h = switch_height + cap_flange - 0.2;               // slight preload, no rattle
rail_lip_y = w + face_t + pcb_t + fit;                          // back of the display PCB
rails_back = rail_lip_y + 1.4;
top_ledge = 2.5;
deck_ledge = 7;
deck_inset = top_ledge + fit;                                   // the deck drops in past the top ledge
led_face_y = rails_back + fit;                                  // LEDs clear the display rails as the deck goes in
led_fin_y = led_face_y + 1.9;                                   // strip + LED height in front of the fin
port_r = port_diameter / 2;

// Chamber volume (approximate) and port length (Helmholtz):
//   Fb = c / (2 pi) * sqrt(A / (V * Leff))
chamber_gross = (W - 2*w) * (inner_back - w) * (deck_z - w);
bosses = 2 * PI * pow(boss_r, 2) * (boss_depth - w) * 0.7;
drivers_in = 2 * PI * pow(speaker_basket_diameter/2, 2) * (speaker_depth - (seat_floor - flange_front)) * 0.5;
port_tube = PI * pow(port_r + port_wall, 2) * 60;
chamber_net_l = (chamber_gross - bosses - drivers_in - (bass_mode == "port" ? port_tube : 0)) / 1e6;
port_leff = PI * pow(port_r / 1000, 2) * pow(343, 2)
            / (4 * pow(PI, 2) * pow(port_tuning_hz, 2) * chamber_net_l / 1000) * 1000;
port_length = max(bt + 5, port_leff - 1.46 * port_r);           // minus both end corrections

echo(str("Outer size: ", W, " x ", D, " x ", H, " mm"));
echo(str("Chamber: ~", round(chamber_net_l * 100) / 100, " L net"));
if (bass_mode == "port")
    echo(str("Port: ", port_diameter, " mm x ", round(port_length), " mm, tuned to ~", port_tuning_hz, " Hz"));

assert(speaker_center_z - speaker_frame_diameter/2 > w + 2, "drivers hit the floor");
assert(speaker_center_z + speaker_frame_diameter/2 < deck_z - 2, "drivers hit the deck");
assert(speaker_center_y - grille_d/2 - fit > r + 1 && speaker_center_y + grille_d/2 + fit < D - r - 1,
       "grilles are wider than the flat part of the sides");
assert(speaker_center_z + grille_d/2 + fit < waist_z - 2, "grilles reach the waist groove");
assert(clamp || speaker_hole_circle/2 - m3_pilot > speaker_basket_diameter/2 + fit,
       "holes mode: the frame's holes are inside the basket; use clamp mode");
assert(2 * (flange_front + speaker_depth) + (bass_mode == "port" ? port_diameter + 2*port_wall + 8 : 0) < W,
       "magnets and port collide in the chamber");
assert(bass_mode != "port" || port_length - bt < panel_y - w - port_diameter,
       "port too long for the chamber; raise port_tuning_hz or use a smaller port_diameter");
assert(window[0] < W - 2*r, "display window wider than the flat front");
assert(pcb_w + 4 < W - 2*w, "display module wider than the inside");

// ---------------------------------------------------------------------------
// Helpers

module rrect(size, radius) {
    rr = max(0.01, min(radius, min(size[0], size[1])/2 - 0.01));
    offset(r = rr) offset(delta = -rr) square(size, center = true);
}

module outline(inset = 0) {
    translate([W/2, D/2]) rrect([W - 2*inset, D - 2*inset], r - inset);
}

module outer_shape() {
    hull() {
        linear_extrude(eps) outline(bottom_chamfer);
        translate([0, 0, bottom_chamfer]) linear_extrude(H - bottom_chamfer - top_chamfer) outline();
        translate([0, 0, H - eps]) linear_extrude(eps) outline(top_chamfer);
    }
}

// the hollow inside the body, seen from above
module cavity_2d() {
    translate([W/2, (w + inner_back)/2]) rrect([W - 2*w, inner_back - w], r - w);
}

// 2D teardrop with its point towards +y
module teardrop_2d(d, cap = 0) {
    intersection() {
        union() {
            circle(d = d);
            rotate(45) square(d/2);
        }
        if (cap > 0) translate([-d, -d]) square([2*d, d + cap]);
    }
}

// horizontal holes that print without support: axis along +x / -y, point up
module teardrop_x(d, length, cap = 0) {
    rotate([0, 90, 0]) linear_extrude(length) rotate(90) teardrop_2d(d, cap);
}

module teardrop_y(d, length, cap = 0) {
    rotate([90, 0, 0]) linear_extrude(length) teardrop_2d(d, cap);
}

// a block against a wall with a 45 degree underside running back to the wall
// (plane y = wall_y, block on the +y or -y side of it)
module chinned_block(p0, p1, wall_y) {
    reach = max(abs(p0[1] - wall_y), abs(p1[1] - wall_y));
    translate(p0) cube(p1 - p0);
    hull() {
        translate(p0) cube([p1[0] - p0[0], p1[1] - p0[1], eps]);
        translate([p0[0], wall_y - eps/2, p0[2] - reach]) cube([p1[0] - p0[0], eps, eps]);
    }
}

module countersink(depth = 10) {
    // M3 flat head, 90 degrees, top of the hole at z = 0
    translate([0, 0, -m3_head/2 + eps]) cylinder(d1 = 0, d2 = m3_head + 2*eps, h = m3_head/2);
    translate([0, 0, -depth]) cylinder(d = m3_clearance, h = depth + 1);
    cylinder(d = m3_head, h = 5);
}

// ---------------------------------------------------------------------------
// Body

function panel_screws() = [for (x = [panel_x0 + frame/2, panel_x1 - frame/2],
                                 z = [w + 8, deck_z - 8, plate_z - 10]) [x, z]];
function deck_screws() = [for (x = [w + deck_inset + 3.8, W - w - deck_inset - 3.8], y = [22, 70]) [x, y]];
function feet() = [for (x = [16, W - 16], y = [16, D - 16]) [x, y]];

module body() {
    difference() {
        union() {
            difference() {
                outer_shape();
                translate([0, 0, w]) linear_extrude(H) cavity_2d();
            }
            intersection() {
                outer_shape();
                body_inside();
            }
        }
        // access opening and the rabbet the back panel sits in; foam tape seals the
        // chamber, the frame above the deck is the hard stop
        translate([open_x0, inner_back - 4, open_z0]) cube([open_x1 - open_x0, D, H]);
        translate([panel_x0, panel_y - seal, w]) cube([panel_x1 - panel_x0, D, deck_top - w]);
        translate([panel_x0, panel_y, w]) cube([panel_x1 - panel_x0, D, H]);
        // the top plate covers the frame
        translate([w, inner_back - r, plate_z]) cube([W - 2*w, panel_y - inner_back + r, H]);
        speaker_sides() speaker_cut();
        display_cut();
        light_cut();
        waist_cut();
        front_groove();
        for (p = panel_screws())
            translate([p[0], panel_y + eps, p[1]]) teardrop_y(insert_diameter, insert_depth + seal + eps);
        for (p = deck_screws())
            translate([p[0], p[1], deck_z + eps]) mirror([0, 0, 1]) cylinder(d = m3_pilot, h = 8);
        for (p = feet()) translate([p[0], p[1], -eps]) cylinder(d = 10.5, h = 1);
    }
}

module body_inside() {
    // the chamber ledge is wide so the slimmer deck still seals on it
    ledge_ring(deck_z, deck_ledge);
    // the display slides down its rails past the top ledge; the rails carry the plate there
    difference() {
        ledge_ring(plate_z, top_ledge);
        translate([W/2 - pcb_w/2 - fit - 1.6 - fit, w - 1, plate_z - top_ledge - 1])
            cube([pcb_w + 2*(2*fit + 1.6), top_ledge + 2, top_ledge + 2]);
    }
    speaker_sides() speaker_boss();

    // back-panel insert pillars beside the opening; the middle pair also carries the
    // deck's back corners
    for (p = panel_screws()) {
        left = p[0] < W/2;
        x0 = left ? w - eps : open_x1;
        x1 = left ? open_x0 : W - w + eps;
        if (p[1] < w + 12)
            translate([x0, inner_back - 6.5, w]) cube([x1 - x0, 6.5, p[1] + 6 - w]);
        else if (p[1] < deck_z)
            chinned_block([x0, deck_corner_y() - 6, p[1] - 6], [x1, inner_back, deck_z], inner_back);
        else
            chinned_block([x0, inner_back - 6.5, p[1] - 6], [x1, inner_back, p[1] + 6], inner_back);
    }

    // deck screw blocks
    for (p = deck_screws()) {
        left = p[0] < W/2;
        x0 = left ? w - eps : p[0] - 3.5;
        x1 = left ? p[0] + 3.5 : W - w + eps;
        chinned_block_x([x0, p[1] - 4, deck_z - 8], [x1, p[1] + 4, deck_z], left ? w : W - w);
    }

    display_rails();
}

// like chinned_block, for blocks on the side walls (wall plane x = wall_x)
module chinned_block_x(p0, p1, wall_x) {
    reach = max(abs(p0[0] - wall_x), abs(p1[0] - wall_x));
    translate(p0) cube(p1 - p0);
    hull() {
        translate(p0) cube([p1[0] - p0[0], p1[1] - p0[1], eps]);
        translate([wall_x - eps/2, p0[1], p0[2] - reach]) cube([eps, p1[1] - p0[1], eps]);
    }
}

// a 45 degree ledge all around the cavity with its top at z
module ledge_ring(z, depth) {
    difference() {
        translate([0, 0, z - depth]) linear_extrude(depth) cavity_2d();
        hull() {
            translate([0, 0, z - depth - eps]) linear_extrude(eps) cavity_2d();
            translate([0, 0, z]) linear_extrude(eps) offset(delta = -depth) cavity_2d();
        }
    }
}

// Features cut into a side wall, in a frame where x = 0 is the outside face and +x
// points into the enclosure along the driver's axis.
module speaker_sides() {
    for (side = [0, 1])
        translate([side ? W : 0, speaker_center_y, speaker_center_z])
            mirror([side, 0, 0]) children();
}

module speaker_boss() {
    // thick ring behind the driver; the chin lets it print upright
    hull() {
        rotate([0, 90, 0]) cylinder(r = boss_r, h = boss_depth);
        translate([0, 0, -(boss_depth - w)]) rotate([0, 90, 0]) cylinder(r = boss_r, h = w);
    }
}

module speaker_cut() {
    // grille recess (round: it is the visible edge)
    translate([-1, 0, 0]) rotate([0, 90, 0]) cylinder(d = grille_d + 2*fit, h = grille_recess + 1);
    // pry notch under the grille
    translate([-1, -3, -(grille_d/2 + fit) - 1.2]) cube([grille_recess + 1, 6, 2]);
    // clamp ring and frame seat; the flat tops bridge instead of overhanging
    if (clamp)
        translate([grille_recess - eps, 0, 0]) teardrop_x(grille_d + 2*fit, ring_t + eps, boss_r - 1.5);
    translate([grille_recess - eps, 0, 0])
        teardrop_x(speaker_frame_diameter + 2*fit, seat_floor - grille_recess, boss_r - 1.5);
    // opening behind the cone, flared at 45 degrees so the back of the cone breathes
    translate([seat_floor - eps, 0, 0]) rotate([0, 90, 0])
        cylinder(d1 = speaker_basket_diameter + 2*fit,
                 d2 = speaker_basket_diameter + 2*fit + 2*(boss_depth - seat_floor + 1),
                 h = boss_depth - seat_floor + 1);
    // screw pilots
    if (clamp)
        for (i = [0 : 3]) rotate([45 + i*90, 0, 0])
            translate([flange_front - eps, 0, ring_screw_circle/2]) rotate([0, 90, 0]) cylinder(d = m3_pilot, h = 8);
    else
        for (i = [0 : speaker_hole_count - 1]) rotate([speaker_hole_angle + i*360/speaker_hole_count, 0, 0])
            translate([seat_floor - eps, 0, speaker_hole_circle/2]) rotate([0, 90, 0]) cylinder(d = m3_pilot, h = 8);
}

module display_cut() {
    translate([W/2, 0, display_center_z]) rotate([-90, 0, 0]) {
        // window recess, flush acrylic
        translate([0, 0, -1]) linear_extrude(window_thickness + 1) rrect(window, 3);
        // opening in front of the active area
        linear_extrude(3*w, center = true) rrect(active + [4, 4], 1.5);
    }
}

module light_cut() {
    translate([W/2, -1, waist_z]) rotate([-90, 0, 0])
        linear_extrude(w + 2) rrect([light_length, light_height], light_height/2);
}

// V groove around the waist, also cut into the back panel
module waist_cut(g = 0.6) {
    translate([0, 0, waist_z]) difference() {
        translate([0, 0, -g - 0.1]) linear_extrude(2*g + 0.2) outline(-2);
        hull() {
            translate([0, 0, -g - 0.1]) linear_extrude(eps) outline(-0.1);
            linear_extrude(eps) outline(g);
        }
        hull() {
            linear_extrude(eps) outline(g);
            translate([0, 0, g + 0.1]) linear_extrude(eps) outline(-0.1);
        }
    }
}

// the top plate's front tongue locks into this groove
tongue = 1.2;
tongue_z = plate_z + 0.3;
tongue_x = [22, W - 22];

module front_groove() {
    translate([tongue_x[0] - 1, 0, 0]) rotate([90, 0, 90]) linear_extrude(tongue_x[1] - tongue_x[0] + 2)
        polygon([[w + eps, tongue_z - fit], [w - tongue - fit, tongue_z - fit],
                 [w - tongue - fit, tongue_z - fit + eps], [w + eps, tongue_z + tongue + 2*fit]]);
}

module display_rails() {
    z0 = pcb_cz - pcb_h/2 - 1.5;
    z1 = plate_z;
    lip_y = w + face_t + pcb_t + fit;
    for (s = [-1, 1]) {
        edge = W/2 + s * (pcb_w/2 + fit);
        outer = edge + s * 1.6;
        inner = edge - s * 1.5;
        // side wall
        chinned_block([min(edge, outer), w - eps, z0], [max(edge, outer), lip_y + 1.4, z1], w);
        // lip behind the PCB
        chinned_block([min(inner, edge), lip_y, z0], [max(inner, edge), lip_y + 1.4, z1], w);
        // stop under the PCB
        chinned_block([min(inner, edge), w - eps, z0], [max(inner, edge), lip_y, z0 + 1.5], w);
    }
}

// ---------------------------------------------------------------------------
// Deck: seals the chamber and carries the Pi and the amplifiers

function pi_holes() = [for (x = [3.5, 26.5], y = [3.5, 61.5]) pi_origin + [x, y]];
function amp_origins() = [[56, 28], [56, 52]];
wire_hole = [50, 84];
led_fin_length = 52;

// the back corners stop in front of the upper insert pillars
function deck_corner_y() = inner_back - 6.5 - fit;

module deck_2d() {
    difference() {
        union() {
            intersection() {
                offset(delta = -deck_inset) cavity_2d();
                square([W, deck_corner_y()]);
            }
            translate([open_x0 + fit, deck_corner_y() - 10])
                square([open_x1 - open_x0 - 2*fit, panel_y - fit - deck_corner_y() + 10]);
        }
        // clearance for the display rails as the deck goes in
        for (s = [-1, 1]) {
            edge = W/2 + s * (pcb_w/2 + fit);
            translate([min(edge - s * 1.5, edge + s * 1.6) - fit, 0]) square([3.1 + 2*fit, rails_back + fit]);
        }
    }
}

module deck() {
    // modelled with its underside at z = 0; printed as is
    difference() {
        union() {
            linear_extrude(deck_thickness) deck_2d();
            for (p = pi_holes()) translate(p) cylinder(d = 6, h = deck_thickness + standoff_height);
            for (a = amp_origins()) translate(a) amp_cradle();
            // the status LED strip sticks to the front of this fin, LEDs facing the slot
            translate([W/2 - led_fin_length/2, led_fin_y, 0]) cube([led_fin_length, 1.5, deck_thickness + 10]);
        }
        for (p = pi_holes()) translate([p[0], p[1], 1]) cylinder(d = m25_pilot, h = 20);
        for (p = deck_screws()) translate([p[0], p[1], deck_thickness]) countersink();
        // speaker wires; seal with hot glue
        translate(wire_hole) cylinder(d = 7, h = 20, center = true);
    }
}

module amp_cradle() {
    difference() {
        translate([-1.2 - fit, -1.2 - fit, 0]) cube([amp_board[0] + 2.4 + 2*fit, amp_board[1] + 2.4 + 2*fit, deck_thickness + 2]);
        translate([-fit, -fit, deck_thickness]) cube([amp_board[0] + 2*fit, amp_board[1] + 2*fit, 5]);
        // wire exits
        translate([amp_board[0]/2 - 5, -5, deck_thickness]) cube([10, amp_board[1] + 10, 5]);
    }
}

// ---------------------------------------------------------------------------
// Top plate: rests on the ledges, front tongue in the body, rear tongue under the back panel

function button_xs() = [for (i = [-1 : 1]) W/2 + i * button_pitch];
function mic_xs() = [W/2 - mic_spacing/2, W/2 + mic_spacing/2];

module plate_2d() {
    offset(delta = -fit) union() {
        cavity_2d();
        translate([w, inner_back - r]) square([W - 2*w, panel_y - inner_back + r]);
    }
}

// D-shaped so the caps cannot turn
module button_hole_2d(d) {
    intersection() {
        circle(d = d);
        translate([-d, -d]) square([2*d, d + d/2 - 0.6]);
    }
}

module top_plate() {
    // modelled with its underside at z = 0; printed upside down
    difference() {
        union() {
            hull() {
                linear_extrude(tt - 0.4) plate_2d();
                linear_extrude(tt) offset(delta = -0.4) plate_2d();
            }
            // tongues, 45 degrees on top
            for (front = [true, false])
                translate([tongue_x[0] + 1, 0, 0]) rotate([90, 0, 90]) linear_extrude(tongue_x[1] - tongue_x[0] - 2)
                    let(y = front ? w + fit : panel_y - fit, s = front ? -1 : 1)
                        polygon([[y - s*eps, 0.3], [y + s*tongue, 0.3], [y - s*eps, 0.3 + tongue]]);
            // switch-strip bosses between the switches
            for (x = [W/2 - button_pitch/2, W/2 + button_pitch/2])
                translate([x, button_y, -switch_boss_h]) cylinder(d = 4.2, h = switch_boss_h + eps);
            // microphone pockets
            for (x = mic_xs()) translate([x - mic_pcb/2 - 2, button_y - mic_pcb/2 - 2, -2.6])
                cube([mic_pcb + 4, mic_pcb + 4, 2.6 + eps]);
        }
        for (x = button_xs()) translate([x, button_y, -1]) linear_extrude(tt + 2)
            button_hole_2d(button_diameter + 2*0.2);
        for (x = [W/2 - button_pitch/2, W/2 + button_pitch/2])
            translate([x, button_y, -switch_boss_h - 1]) cylinder(d = m2_pilot, h = switch_boss_h);
        for (x = mic_xs()) {
            translate([x, button_y, -5]) cylinder(d = mic_port_diameter, h = 10);
            translate([x - mic_pcb/2 - fit, button_y - mic_pcb/2 - fit, -2.6 - eps])
                cube([mic_pcb + 2*fit, mic_pcb + 2*fit, 2.6]);
        }
    }
}

// ---------------------------------------------------------------------------
// Back panel

module back_panel() {
    // modelled in place (outside face at y = D); printed outside face down
    difference() {
        union() {
            intersection() {
                outer_shape();
                translate([panel_x0 + fit, panel_y, w + fit]) cube([panel_x1 - panel_x0 - 2*fit, bt, H]);
            }
            // rib under the deck's back edge
            translate([open_x0 + fit, panel_y - 3, deck_z - 3]) cube([open_x1 - open_x0 - 2*fit, 3 + eps, 3 - 0.2]);
            if (bass_mode == "port")
                translate([W/2, panel_y + eps, speaker_center_z]) rotate([90, 0, 0])
                    cylinder(r = port_r + port_wall, h = port_length - bt);
            // USB-C breakout shelf
            translate([usbc_x, panel_y, usbc_z]) usbc_shelf();
            // mute switch bosses
            for (dx = [-9, 9]) translate([mute_x + dx, panel_y + eps, mute_z]) rotate([90, 0, 0])
                cylinder(d = 4.2, h = switch_boss_h + eps);
        }
        waist_cut();
        // groove for the top plate's rear tongue
        translate([tongue_x[0] - 1, 0, 0]) rotate([90, 0, 90]) linear_extrude(tongue_x[1] - tongue_x[0] + 2)
            polygon([[panel_y - eps, tongue_z - fit], [panel_y + tongue + fit, tongue_z - fit],
                     [panel_y + tongue + fit, tongue_z - fit + eps], [panel_y - eps, tongue_z + tongue + 2*fit]]);
        if (bass_mode == "port")
            translate([W/2, D + 1, speaker_center_z]) rotate([90, 0, 0]) {
                cylinder(r = port_r, h = port_length + 2);
                cylinder(r1 = port_r + 4, r2 = port_r, h = 4);          // flared mouth, 45 degrees
            }
        if (bass_mode == "passive_radiator")
            translate([W/2, D, speaker_center_z]) rotate([90, 0, 0]) {
                cylinder(d = radiator_cutout, h = 20, center = true);
                for (i = [0 : radiator_hole_count - 1]) rotate(45 + i*360/radiator_hole_count)
                    translate([radiator_hole_circle/2, 0, 0]) cylinder(d = m3_pilot, h = 20, center = true);
            }
        // vents over the electronics
        for (i = [0 : 4])
            translate([W/2, D + 1, 112 + i*6]) rotate([90, 0, 0]) linear_extrude(bt + 2) rrect([32, 2.4], 1.2);
        // USB-C: receptacle opening plus a pocket for the plug's overmould
        translate([usbc_x, D + 1, usbc_z]) rotate([90, 0, 0]) {
            linear_extrude(bt + 2) rrect([9.4, 3.8], 1.2);
            linear_extrude(4) rrect([13, 7.4], 2.4);
        }
        // mute button
        translate([mute_x, D + 1, mute_z]) rotate([90, 0, 0]) linear_extrude(bt + 2)
            button_hole_2d(button_diameter + 2*0.2);
        for (dx = [-9, 9]) translate([mute_x + dx, panel_y - switch_boss_h - 1.5, mute_z]) rotate([-90, 0, 0])
            cylinder(d = m2_pilot, h = switch_boss_h);
        // screws
        for (p = panel_screws()) translate([p[0], D, p[1]]) rotate([-90, 0, 0]) countersink();
        // name
        translate([W/2, D - 0.4, 18]) rotate([90, 0, 0]) rotate([0, 180, 0]) linear_extrude(1)
            text("OPEN SPEAKER", size = 3.6, font = "Liberation Sans:style=Bold", halign = "center",
                 valign = "center", spacing = 1.15);
    }
}

module usbc_shelf() {
    // the breakout rests on this shelf with its receptacle against the panel
    b = usbc_board;
    below = 1.6 + 3.26/2;                                   // PCB + half the receptacle
    translate([-b[0]/2 - 1.6, -b[1], -below - 2]) difference() {
        cube([b[0] + 3.2, b[1] + eps, 2 + 2]);
        translate([1.6 - fit, -1, 2]) cube([b[0] + 2*fit, b[1] + 2, 3]);
    }
}

// ---------------------------------------------------------------------------
// Small parts

module grille() {
    // printed flat, outside face down; crush ribs make it a press fit
    d = grille_d + 2*fit - 0.3;
    difference() {
        union() {
            cylinder(d = d, h = grille_thickness);
            for (i = [0 : 7]) rotate(22.5 + i*45) translate([d/2, 0, 0]) cylinder(d = 0.9, h = grille_thickness, $fn = 12);
        }
        translate([0, 0, -1]) grille_holes(d - 6);
    }
}

module grille_holes(pattern_d) {
    R = pattern_d / 2;
    if (grille_pattern == "rings") {
        hole = 2.4;
        for (ring = [0 : floor((R - hole/2) / 3.6)]) {
            rr = ring * 3.6;
            n = ring == 0 ? 1 : floor(2 * PI * rr / 3.6);
            for (i = [0 : n - 1]) rotate(i * 360 / n) translate([rr, 0, 0]) cylinder(d = hole, h = 5, $fn = 16);
        }
    } else {
        pitch = 4.0;
        hole = 3.4;                                          // across corners
        n = ceil(R / pitch) + 1;
        for (j = [-n : n], i = [-n : n]) {
            c = [i * pitch + (j % 2) * pitch/2, j * pitch * sqrt(3)/2];
            if (norm(c) + hole/2 <= R) translate(c) rotate(30) cylinder(d = hole, h = 5, $fn = 6);
        }
    }
}

module clamp_ring() {
    // printed flat; countersunk M3 x 8 into the side wall
    difference() {
        cylinder(d = ring_od, h = ring_t);
        translate([0, 0, -1]) cylinder(d = speaker_cone_diameter + 1, h = ring_t + 2);
        for (i = [0 : 3]) rotate(45 + i*90) translate([ring_screw_circle/2, 0, ring_t]) countersink();
    }
}

module button_cap(plate_t, symbol) {
    // modelled upright; printed upside down with the symbol on the bed
    h = cap_flange + plate_t + cap_proud;
    difference() {
        union() {
            intersection() {
                hull() {
                    cylinder(d = button_diameter, h = h - 0.4);
                    cylinder(d = button_diameter - 0.8, h = h);
                }
                linear_extrude(h) button_hole_2d(button_diameter);
            }
            cylinder(d = cap_flange_d, h = cap_flange);
        }
        translate([0, 0, h - 0.4]) linear_extrude(1) cap_symbol(symbol);
    }
}

module cap_symbol(symbol) {
    if (symbol == "minus" || symbol == "plus") square([4, 0.9], center = true);
    if (symbol == "plus") square([0.9, 4], center = true);
    if (symbol == "dot") circle(d = 1.8, $fn = 24);
    if (symbol == "ring") difference() { circle(d = 3.4, $fn = 32); circle(d = 1.8, $fn = 32); }
}

module caps() {
    // all four, upside down with their tops on the bed
    for (c = [[0, tt, "minus"], [1, tt, "dot"], [2, tt, "plus"], [3, bt, "ring"]])
        translate([c[0] * 16, 0, cap_flange + c[1] + cap_proud]) rotate([180, 0, 0]) button_cap(c[1], c[2]);
}

module diffuser() {
    // light pipe from the LEDs to the slot, pushed in from the front after the deck;
    // white or natural PETG, printed lying flat
    rotate([90, 0, 0]) linear_extrude(led_face_y - 0.6, center = true)
        rrect([light_length - 2*0.15, light_height - 2*0.15], light_height/2);
}

module window_insert() {
    // if you print the window instead of cutting acrylic: smoke or clear PETG, 100% infill
    linear_extrude(window_thickness) rrect(window - [2*fit, 2*fit], 3 - fit);
}

module port_plug() {
    // turns the port into a sealed box
    cylinder(r = port_r - 0.15, h = 12);
    cylinder(r = port_r + 3.5, h = 1.5);
}

// ---------------------------------------------------------------------------
// Ghost parts (assembly views and collision checks)

module ghost_driver() {
    // x = 0 at the front of the flange, +x into the enclosure
    rotate([0, 90, 0]) {
        cylinder(d = speaker_frame_diameter, h = speaker_flange_thickness);
        translate([0, 0, speaker_flange_thickness])
            cylinder(d1 = speaker_basket_diameter, d2 = speaker_magnet_diameter, h = speaker_depth * 0.55);
        cylinder(d = speaker_magnet_diameter, h = speaker_depth);
    }
}

module ghost_cone() {
    rotate([0, 90, 0]) translate([0, 0, 0.5]) cylinder(d1 = speaker_cone_diameter - 2, d2 = 18, h = 5);
}

module ghost_pi() {
    translate([pi_origin[0], pi_origin[1], deck_top + standoff_height]) {
        color("#1f7a3a") cube([30, 65, 1.4]);
        color("#222") translate([30 - 3.5 - 2.5 - 2.54, 7, 1.4]) cube([5.08, 50.8, 8.5]);    // GPIO header
        color("silver") translate([10, 65 - 11.5, 1.4]) cube([12, 11.5 + 2.5, 1.4]);     // microSD
        color("#555") translate([12, 22, 1.4]) cube([8, 8, 1.2]);                         // SoC
    }
}

// on the deck (deck coordinates: z = 0 is the underside of the deck)
module ghost_deck_parts() {
    color("#3b5bb5") for (a = amp_origins())
        translate([a[0], a[1], deck_thickness]) cube([amp_board[0], amp_board[1], 1.6]);
    translate([pi_origin[0], pi_origin[1], deck_thickness + standoff_height]) {
        color("#1f7a3a") cube([30, 65, 1.4]);
        color("#222") translate([30 - 3.5 - 2.5 - 2.54, 7, 1.4]) cube([5.08, 50.8, 8.5]);   // GPIO header
        color("silver") translate([10, 65 - 11.5, 1.4]) cube([12, 11.5 + 2.5, 1.4]);    // microSD
    }
    // status LED strip on the fin, LEDs facing the slot
    translate([W/2 - 25, led_fin_y - 0.3, deck_thickness]) {
        color("white") cube([50, 0.3, 10]);
        for (i = [-1 : 1]) color("#eee") translate([25 + i * 16.67 - 2.5, -1.6, 2.5]) cube([5, 1.6, 5]);
    }
}

// on the front wall
module ghost_display() {
    translate([W/2, w, pcb_cz]) {
        color("#2a55a8") translate([-pcb_w/2, face_t, -pcb_h/2]) cube([pcb_w, pcb_t, pcb_h]);
        color("#050505") translate([-display[3]/2, 0, display[8] - display[4]/2]) cube([display[3], face_t, display[4]]);
    }
}

// under the top plate (plate coordinates: z = 0 is the underside of the plate)
module ghost_plate_parts() {
    translate([W/2 - 24.8, button_y - 6, -switch_boss_h - 1.6]) {
        color("#b88a3d") cube([49.6, 12, 1.6]);
        for (x = button_xs()) color("#222") translate([x - (W/2 - 24.8) - 3, 3, 1.6]) {
            cube([6, 6, 3.5]);
            translate([3, 3, 0]) cylinder(d = 3.5, h = switch_height - 0.2, $fn = 16);
        }
    }
    for (x = mic_xs()) color("#3a4fa0") translate([x - mic_pcb/2, button_y - mic_pcb/2, -0.5 - 1.6])
        cube([mic_pcb, mic_pcb, 1.6]);
}

// on the back panel (in place)
module ghost_panel_parts() {
    color("#1b1b8f") translate([usbc_x - usbc_board[0]/2, panel_y - usbc_board[1], usbc_z - 1.6 - 3.26/2])
        cube([usbc_board[0], usbc_board[1], usbc_board[2]]);
    color("silver") translate([usbc_x - 4.47, panel_y - 7.35, usbc_z - 1.63]) cube([8.94, 7.35, 3.26]);
    color("#b88a3d") translate([mute_x - 12, panel_y - switch_boss_h - 1.6, mute_z - 7]) cube([24, 1.6, 14]);
    color("#222") translate([mute_x - 3, panel_y - switch_boss_h, mute_z - 3]) {
        cube([6, 3.5, 6]);
        translate([3, 0, 3]) rotate([-90, 0, 0]) cylinder(d = 3.5, h = switch_height - 0.2, $fn = 16);
    }
}

// the drivers, in place
module ghost_drivers(out = 0) {
    speaker_sides() translate([flange_front - out, 0, 0]) {
        color("#1c1c1c") ghost_driver();
        color("#2a2a2a") ghost_cone();
    }
}

module ghost_display_content() {
    // what the OLED shows, drawn on the window for the renders
    c = "#ffab2e";
    translate([W/2, -0.05, display_center_z]) rotate([90, 0, 0]) color(c) linear_extrude(0.05) {
        a = active;
        translate([a[0]/2 - 1, a[1]/2 - 1.2]) text("7:42", size = a[1] * 0.42, font = "Liberation Sans:style=Bold",
                                                   halign = "right", valign = "top");
        translate([-a[0]/2 + 0.8, a[1]/2 - 1.8]) text("PM", size = a[1] * 0.12, font = "Liberation Sans:style=Bold",
                                                     valign = "top");
        translate([a[0]/2 - 1, -a[1]/2 + 0.8]) text("72°", size = a[1] * 0.24, font = "Liberation Sans:style=Bold",
                                                    halign = "right", valign = "bottom");
    }
}

// ---------------------------------------------------------------------------
// Views

palette = colorway == "dark"
    ? ["#2d2e31", "#3a3b3f", "#8d8f94", "#1a1a1a"]           // body, panels, grilles, caps
    : ["#e9e6df", "#dedad2", "#3b3c3f", "#3b3c3f"];

module in_place_grilles(out = 0) {
    speaker_sides() {
        color(palette[2]) translate([grille_recess - grille_thickness - out, 0, 0]) rotate([0, 90, 0]) grille();
        if (clamp) color("#555") translate([flange_front - out * 0.6, 0, 0]) rotate([0, -90, 0])
            clamp_ring();
    }
}

module in_place_caps(up = 0) {
    for (i = [0 : 2]) translate([button_xs()[i], button_y, plate_z - cap_flange + up])
        color(palette[3]) button_cap(tt, ["minus", "dot", "plus"][i]);
    translate([mute_x, panel_y - cap_flange + up * 0.3, mute_z]) rotate([-90, 0, 0]) rotate([0, 0, 180])
        color(palette[3]) button_cap(bt, "ring");
}

module in_place_window(out = 0) {
    translate([W/2, -out, display_center_z]) rotate([-90, 0, 0])
        color("#0c0c0d") window_insert();
    translate([0, -out, 0]) ghost_display_content();
    translate([W/2, (0.6 + led_face_y)/2 - out * 0.5, waist_z]) color("#bfe6ff") diffuser();
}

module assembly(explode = 0) {
    color(palette[0]) body();
    ghost_display();
    translate([0, 0, deck_z + explode * 0.9]) {
        color(palette[1]) deck();
        ghost_deck_parts();
    }
    translate([0, 0, plate_z + explode * 1.9]) {
        color(palette[0]) top_plate();
        ghost_plate_parts();
    }
    translate([0, 0, explode * 1.9]) in_place_caps(explode * 0.3);
    translate([0, explode * 1.2, 0]) {
        color(palette[1]) back_panel();
        ghost_panel_parts();
    }
    in_place_grilles(explode);
    in_place_window(explode * 0.6);
    ghost_drivers(explode * 0.35);
}

module print_layout() {
    // every part in its print orientation (not one plate: the body alone fills most beds)
    color(palette[0]) body();
    color(palette[1]) translate([W + 20, 0, 0]) deck();
    color(palette[0]) translate([W + 20, 2*D + 30, 0]) rotate([180, 0, 0]) translate([0, 0, -tt]) top_plate();
    color(palette[1]) translate([2*W + 40, 0, 0]) rotate([-90, 0, 0]) translate([0, -D, 0]) back_panel();
    for (i = [0, 1]) color(palette[2]) translate([3*W + 40 + grille_d/2, grille_d/2 + i * (grille_d + 10), 0]) grille();
    for (i = [0, 1]) color("#555") translate([3*W + 50 + 1.5*grille_d, ring_od/2 + i * (ring_od + 10), 0]) clamp_ring();
    color(palette[3]) translate([0, -30, 0]) caps();
    color("#bfe6ff") translate([100, -30, (light_height - 0.3)/2]) diffuser();
    color("#101010") translate([150, -30, 0]) window_insert();
}

if (part == "assembly") assembly();
else if (part == "exploded") assembly(40);
else if (part == "section") difference() { assembly(); translate([-1, -1, -1]) cube([W/2 + 1, D + 60, H + 100]); }
else if (part == "section_front") difference() { assembly(); translate([-50, -50, -1]) cube([W + 100, speaker_center_y + 50, H + 100]); }
else if (part == "print_layout") print_layout();
else if (part == "body") body();
else if (part == "deck") deck();
else if (part == "top_plate") rotate([180, 0, 0]) translate([0, 0, -tt]) top_plate();
else if (part == "back_panel") rotate([-90, 0, 0]) translate([0, -D, 0]) back_panel();
else if (part == "grille") grille();
else if (part == "clamp_ring") clamp_ring();
else if (part == "caps") caps();
else if (part == "diffuser") translate([0, 0, (light_height - 0.3)/2]) diffuser();
else if (part == "window") window_insert();
else if (part == "port_plug") port_plug();
