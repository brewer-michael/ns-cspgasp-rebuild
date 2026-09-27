#!/usr/bin/env bash
# Export every printable part of main_body.scad to STL, optionally rendering the
# documentation images too. Extra arguments go straight to OpenSCAD, so you can
# export with your own measurements without editing the file:
#
#   ./export.sh
#   ./export.sh -D speaker_frame_diameter=53 -D 'bass_mode="sealed"'
#   ./export.sh --images            # also refresh docs/images/enclosure-*.png
#
# STLs go to ./stl (set OUT=... to change). Needs OpenSCAD 2021.01 or newer; on a
# machine without a display, --images also needs xvfb-run.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
scad="$here/main_body.scad"
out="${OUT:-$here/stl}"
images_dir="$here/../../docs/images"
images=false
args=()
for arg in "$@"; do
    case "$arg" in
        --images) images=true ;;
        *) args+=("$arg") ;;
    esac
done

command -v openscad >/dev/null || { echo "openscad not found" >&2; exit 1; }
mkdir -p "$out"

# grille and clamp_ring: print two of each; esp32_cradle only for the ESP32-S3 brain
parts=(body deck top_plate back_panel grille clamp_ring caps diffuser port_plug window esp32_cradle)
log="$(mktemp)"
trap 'rm -f "$log"' EXIT
for part in "${parts[@]}"; do
    echo "== $part"
    if ! openscad -o "$out/$part.stl" -D "part=\"$part\"" ${args[@]+"${args[@]}"} "$scad" >"$log" 2>&1; then
        grep -E "ERROR|WARNING" "$log" >&2 || cat "$log" >&2
        exit 1
    fi
    grep -E "WARNING" "$log" || true
done
grep -E "^ECHO" "$log" | sed 's/^ECHO: "\(.*\)"$/\1/'
echo "STL files in $out"

$images || exit 0

run=(openscad)
if [ -z "${DISPLAY:-}" ] && command -v xvfb-run >/dev/null; then
    run=(xvfb-run -a openscad)
fi
mkdir -p "$images_dir"
render() {  # name part camera [openscad args]
    local name=$1 part=$2 camera=$3
    shift 3
    "${run[@]}" -o "$images_dir/$name.png" --imgsize=1200,1200 --colorscheme=Tomorrow \
        --camera="$camera" --viewall --autocenter -D "part=\"$part\"" "$@" \
        ${args[@]+"${args[@]}"} "$scad" >/dev/null 2>&1
    if command -v convert >/dev/null; then
        convert "$images_dir/$name.png" -trim +repage -bordercolor "#f8f8f8" -border 24 "$images_dir/$name.png"
    fi
    echo "rendered $name.png"
}
render enclosure-front assembly 210,-190,190,50,50,80
render enclosure-front-dark assembly 210,-190,190,50,50,80 -D 'colorway="dark"'
render enclosure-back assembly -150,330,220,50,50,80
render enclosure-exploded exploded 260,-230,220,50,50,90
render enclosure-section section -250,60,120,50,50,80
render enclosure-print-layout print_layout 330,-260,330,150,100,0
