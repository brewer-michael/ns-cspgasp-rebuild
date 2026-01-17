// Insignia NS-CSPGASP "Landscape" Bracket
// CORRECTION: LANDSCAPE ORIENTATION (Horizontal).
// FIT: Pi (65mm) fits across Chassis (66mm).
// LAYOUT:
// - Bottom: Pi Zero 2 W (Horizontal). GPIO Header facing UP.
// - Top: HAT Breakout (Horizontal).
// - Top Rear: DAC Backpack.

$fn = 60;

// --- DIMS ---
chassis_w = 66; 
chassis_h = 80;
screw_dia = 3.4;

// Component Mounting Patterns
// PI ZERO (Landscape)
// Holes are 58mm apart horizontally, 23mm vertically.
pi_mount_w = 58; 
pi_mount_h = 23;

module suspension_frame() {
    union() {
        // 1. OUTER FRAME
        difference() {
            hull() {
                for(x=[-1,1]) for(y=[-1,1])
                    translate([x*chassis_w/2, y*chassis_h/2, 0]) cylinder(h=2, r=5, center=true);
            }
            // Cutout
            rounded_rect([chassis_w-12, chassis_h-12, 10], 2);
            // Chassis Holes
            for(x=[-1,1]) for(y=[-1,1])
                translate([x*chassis_w/2, y*chassis_h/2, 0]) cylinder(h=10, r=screw_dia/2, center=true);
        }
        
        // 2. PI MOUNTING BARS (Bottom Zone - Landscape)
        // Spans left-to-right to grab the wide mounting holes (58mm)
        translate([0, -20, 0]) { // Shifted Down
             difference() {
                 union() {
                     // Top Bar of Pi Mount
                     translate([0, pi_mount_h/2, 0]) cube([64, 5, 2], center=true);
                     // Bottom Bar of Pi Mount
                     translate([0, -pi_mount_h/2, 0]) cube([64, 5, 2], center=true);
                     // Vertical Links (Sides)
                     translate([-30, 0, 0]) cube([4, 25, 2], center=true);
                     translate([30, 0, 0]) cube([4, 25, 2], center=true);
                 }
                 // Mounting Holes
                 for(x=[-1,1]) for(y=[-1,1])
                    translate([x*pi_mount_w/2, y*pi_mount_h/2, 0]) cylinder(h=10, r=1.25, center=true);
             }
        }
        
        // 3. HAT MOUNTING (Top Zone)
        translate([0, 25, 0]) {
             difference() {
                 // Cross Bar
                 cube([40, 6, 2], center=true);
                 // Holes (20mm spacing)
                 translate([-10, 0, 0]) cylinder(h=10, r=1, center=true);
                 translate([10, 0, 0]) cylinder(h=10, r=1, center=true);
             }
        }
        
        // 4. DAC CAGE (Rear Top Zone)
        translate([0, 25, -4]) { 
             difference() {
                 cube([45, 18, 6], center=true);
                 cube([41, 14, 10], center=true);
             }
             // Studs
             translate([-12, 0, 0]) cylinder(h=4, r=2, center=true);
             translate([12, 0, 0]) cylinder(h=4, r=2, center=true);
        }
    }
}

module visualize_landscape() {
    // Pi Zero (Green) - Horizontal
    // GPIO Header should be at the TOP alignment.
    translate([0, -20, 1.6]) {
        color("green") cube([65, 30, 1.6], center=true); // PCB
        
        // GPIO Header (Black) - RIGHT ANGLE (Low Profile)
        // Sits flat against PCB. Height ~2.5mm. Pin direction: UP (Towards HAT).
        translate([0, 12, 1.6/2 + 1.25]) color("black") cube([50, 5, 2.5], center=true);
        // The Pins sticking OUT (Gold)
        translate([0, 15, 1.6/2 + 1.25]) color("gold") cube([50, 6, 0.6], center=true);
        // Wire Path Visualizer (Grey)
        %translate([0, 20, 2]) color("grey", 0.5) cube([40, 10, 2], center=true); 
        
        // USB Ports (Silver) - Bottom Edge
        translate([-6, -15, 2]) color("silver") cube([8, 6, 3], center=true);
        translate([6, -15, 2]) color("silver") cube([8, 6, 3], center=true);
    }
    
    // HAT (Purple)
    translate([0, 25, 2]) color("purple") cube([26, 20, 1.6], center=true); 
    
    // DACs (Blue)
    translate([-12, 25, -4]) color("blue") cube([15, 18, 5], center=true);
    translate([12, 25, -4]) color("blue") cube([15, 18, 5], center=true);
}

// Utility
module rounded_rect(size, radius) {
    x = size[0]; y = size[1]; z = size[2];
    cube(size, center=true); 
}

// RENDER
suspension_frame();
visualize_landscape();
