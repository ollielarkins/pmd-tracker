#!/usr/bin/env bash
# Regenerate the KiCad project from design.py, autoroute, check, and export fab files.
# Needs KiCad 10, Java 21 and freerouting-1.9.0.jar (paths overridable below).
set -euo pipefail
cd "$(dirname "$0")"
KB="${KICAD_BIN:-/c/Users/ozzal/AppData/Local/Programs/KiCad/10.0/bin}"
JAVA="${JAVA:-java}"
FREEROUTING="${FREEROUTING:?set FREEROUTING to the path of freerouting-1.9.0.jar}"
PY="$KB/python.exe"; CLI="$KB/kicad-cli.exe"; K=kicad; N=pmd-tracker

"$PY" generate.py schematic
"$CLI" sch erc --severity-all --exit-code-violations -o $K/erc.rpt $K/$N.kicad_sch
"$CLI" sch export netlist --format kicadxml -o $K/netlist.xml $K/$N.kicad_sch
"$PY" generate.py check

# Freerouting is not deterministic: retry until a run closes every connection and DRC is clean.
for attempt in 1 2 3 4 5; do
  "$PY" generate.py pcb
  "$JAVA" -jar "$FREEROUTING" -de $K/$N.dsn -do $K/$N.ses -mp 100
  "$PY" generate.py finish
  if "$CLI" pcb drc --severity-error --schematic-parity --refill-zones --save-board --exit-code-violations        -o $K/drc.rpt $K/$N.kicad_pcb; then break; fi
  [ "$attempt" = 5 ] && { echo "routing did not converge, see $K/drc.rpt"; exit 1; }
done

"$CLI" pcb drc --severity-all --schematic-parity -o $K/drc.rpt $K/$N.kicad_pcb  # full report, warnings included
rm -rf fab && mkdir -p fab/gerbers
"$CLI" pcb export gerbers -o fab/gerbers --layers F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts $K/$N.kicad_pcb
"$CLI" pcb export drill -o fab/gerbers/ $K/$N.kicad_pcb
"$CLI" sch export bom -o bom.csv --fields 'Reference,Value,MPN,Footprint,${QUANTITY}' --labels 'Reference,Value,MPN,Footprint,Qty' --group-by Value,Footprint $K/$N.kicad_sch
"$CLI" pcb render -o ../docs/board-top.png --side top --quality high --width 1600 --height 1100 $K/$N.kicad_pcb
"$CLI" pcb render -o ../docs/board-bottom.png --side bottom --quality high --width 1600 --height 1100 $K/$N.kicad_pcb
(cd fab && rm -f $N-gerbers.zip && "$PY" -c "import shutil; shutil.make_archive('$N-gerbers', 'zip', 'gerbers')")
rm -rf $K/$N.dsn $K/$N.ses $K/netlist.xml logs $K/logs __pycache__
echo done
