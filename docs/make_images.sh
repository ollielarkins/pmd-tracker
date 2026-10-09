#!/usr/bin/env bash
# Regenerate docs/images from the KiCad project. Every image is a direct export of the real design.
set -euo pipefail
cd "$(dirname "$0")"
KB="${KICAD_BIN:-/c/Users/ozzal/AppData/Local/Programs/KiCad/10.0/bin}"
CLI="$KB/kicad-cli.exe"
PCB=../hardware/kicad/pmd-tracker.kicad_pcb
SCH=../hardware/kicad/pmd-tracker.kicad_sch
O=images
rm -rf $O && mkdir -p $O

render() { "$CLI" pcb render -o "$O/$1" --quality high --width 1600 --height 1100 "${@:2}" $PCB; }
render 01-render-top.png --side top
render 02-render-bottom.png --side bottom
render 03-render-iso-front.png --rotate '-45,0,30' --perspective --zoom 0.9
render 04-render-iso-back.png --rotate '-45,0,210' --perspective --zoom 0.9
render 05-render-side.png --rotate '-80,0,0' --perspective --zoom 1.1
render 06-render-closeup-sensors.png --side top --zoom 3 --pan '-1.2,1.8,0'
render 07-render-closeup-power.png --side top --zoom 3 --pan '1.85,-0.3,0'

"$CLI" sch export svg -o "$O" $SCH
mv "$O/pmd-tracker.svg" "$O/08-schematic.svg"

layer() { "$CLI" pcb export svg --mode-single --page-size-mode 2 --exclude-drawing-sheet --drill-shape-opt 2 \
            -l "$2,Edge.Cuts" -o "$O/$1" $PCB; }
layer 09-layer-F_Cu.svg F.Cu
layer 10-layer-In1_Cu-GND.svg In1.Cu
layer 11-layer-In2_Cu-3V3.svg In2.Cu
layer 12-layer-B_Cu.svg B.Cu
"$CLI" pcb export svg --mode-single --page-size-mode 2 --exclude-drawing-sheet --sp \
  -l F.Fab,Edge.Cuts -o "$O/13-assembly-F_Fab.svg" $PCB

"$CLI" fp export svg --fp ADI_LGA-16_3x3.25mm_P0.5mm --sp -l F.Cu,F.Fab,F.SilkS,F.CrtYd \
  -o "$O" ../hardware/kicad/pmd.pretty
mv "$O/ADI_LGA-16_3x3.25mm_P0.5mm.svg" "$O/14-footprint-ADXL372.svg"
cp block-diagram.svg "$O/15-block-diagram.svg"

# Everything as PNG: rasterise the SVG exports, then drop them.
python svg2png.py 4000 "$O/08-schematic.svg"
python svg2png.py 1600 "$O"/09-*.svg "$O"/1[0-5]-*.svg
rm -f "$O"/*.svg
ls $O
