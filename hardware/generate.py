"""Build the KiCad project in hardware/kicad from design.py.

Run with KiCad's bundled Python (it provides pcbnew):
    "<KiCad>/bin/python.exe" generate.py schematic   # symbols, footprint, project, .kicad_sch
    "<KiCad>/bin/python.exe" generate.py pcb         # placed + planed board, DSN for routing
    "<KiCad>/bin/python.exe" generate.py finish      # import routed SES, pours, outline text
"""
import json
import os
import re
import sys
import uuid

from design import BOARD_H, BOARD_W, CLEARANCE, CORNER_R, DEFAULT_TRACK, MPN, NETCLASSES, PARTS, PWR_FLAGS, VIA_D, VIA_DRILL, nets

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "kicad")
NAME = "pmd-tracker"
KICAD = os.environ.get("KICAD_SHARE", r"C:\Users\ozzal\AppData\Local\Programs\KiCad\10.0\share\kicad")
SYM_DIR, FP_DIR = os.path.join(KICAD, "symbols"), os.path.join(KICAD, "footprints")
ROOT_UUID = "6f3b9c2e-4d1a-4e7b-9a55-1c2d3e4f5a60"  # fixed so regenerated files diff cleanly
OX, OY = 100.0, 100.0  # board origin on the PCB canvas


def uid(seed):
    return str(uuid.uuid5(uuid.UUID(ROOT_UUID), seed))


# ---------- s-expression helpers ----------

def block_at(text, i):
    """Return the balanced (...) block starting at text[i]."""
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    raise ValueError("unbalanced")


def top_blocks(block, head):
    """Direct child blocks of `block` that start with `(head`."""
    out, depth, i = [], 0, 0
    while i < len(block):
        c = block[i]
        if c == "(":
            if depth == 1 and block.startswith("(" + head, i) and block[i + 1 + len(head)] in " \n\t":
                b = block_at(block, i)
                out.append(b)
                i += len(b)
                continue
            depth += 1
        elif c == ")":
            depth -= 1
        i += 1
    return out


_lib_cache = {}


def lib_symbol(lib_id):
    """Flattened symbol text from a KiCad .kicad_sym, renamed to the full lib_id."""
    lib, name = lib_id.split(":")
    path = os.path.join(SYM_DIR, lib + ".kicad_sym") if lib != "pmd" else os.path.join(OUT, "pmd.kicad_sym")
    if path not in _lib_cache:
        _lib_cache[path] = open(path, encoding="utf-8").read()
    text = _lib_cache[path]
    blk = block_at(text, text.index(f'(symbol "{name}"'))
    m = re.search(r'\(extends "([^"]+)"\)', blk)
    if m:
        parent = m.group(1)
        pblk = block_at(text, text.index(f'(symbol "{parent}"'))
        assert "(extends" not in pblk, "two-level extends not handled"
        for p in top_blocks(pblk, "property"):
            pblk = pblk.replace(p, "", 1)
        props = "\n".join(top_blocks(blk, "property"))
        pblk = pblk.replace(f'(symbol "{parent}"', f'(symbol "{name}"\n{props}', 1)
        blk = pblk.replace(f'"{parent}_', f'"{name}_')
    return blk.replace(f'(symbol "{name}"', f'(symbol "{lib_id}"', 1)


def pins_of(sym_text):
    """{number: (x, y, angle)} in symbol coordinates (y up)."""
    out = {}
    for p in re.finditer(r'\(pin \w+ \w+\s*\(at ([-\d.]+) ([-\d.]+) (\d+)\).*?\(number "([^"]*)"', sym_text, re.S):
        out[p.group(4)] = (float(p.group(1)), float(p.group(2)), int(p.group(3)))
    return out


# ---------- project symbol + footprint library ----------

def make_symbol(name, ref, fp, desc, left, right, w=15.24):
    """Box symbol. left/right: [(number, name, etype)] top to bottom."""
    n = max(len(left), len(right))
    h = (n + 1) * 2.54
    top = round(h / 2 / 2.54) * 2.54
    pins = []
    for side, lst in ((-1, left), (1, right)):
        for k, (num, pname, etype) in enumerate(lst):
            x = side * (w / 2 + 2.54)
            y = top - 2.54 * (k + 1)
            ang = 0 if side < 0 else 180
            pins.append(f'(pin {etype} line (at {x:.2f} {y:.2f} {ang}) (length 2.54) '
                        f'(name "{pname}" (effects (font (size 1.27 1.27)))) '
                        f'(number "{num}" (effects (font (size 1.27 1.27)))))')
    prop = lambda k, v, y, hide: (f'(property "{k}" "{v}" (at 0 {y:.2f} 0)' + (" (hide yes)" if hide else "")
                                  + ' (effects (font (size 1.27 1.27))))')
    return (f'(symbol "{name}" (pin_names (offset 1.016)) (exclude_from_sim no) (in_bom yes) (on_board yes)\n'
            + prop("Reference", ref, top + 1.27, False) + "\n"
            + prop("Value", name, -top - 1.27, False) + "\n"
            + prop("Footprint", fp, -top - 3.81, True) + "\n"
            + prop("Datasheet", "", 0, True) + "\n"
            + prop("Description", desc, 0, True) + "\n"
            + f'(symbol "{name}_0_1" (rectangle (start {-w / 2:.2f} {top:.2f}) (end {w / 2:.2f} {-top:.2f}) '
              f'(stroke (width 0.254) (type default)) (fill (type background))))\n'
            + f'(symbol "{name}_1_1" ' + "\n".join(pins) + "))")


def write_pmd_lib():
    adxl = make_symbol(
        "ADXL372", "U", "pmd:ADI_LGA-16_3x3.25mm_P0.5mm", "ADXL372 +/-200 g 3-axis accelerometer, SPI",
        [("14", "VS", "power_in"), ("1", "VDDIO", "power_in"), ("8", "~{CS}/SCL", "input"),
         ("4", "SCLK", "input"), ("6", "MOSI/SDA", "bidirectional"), ("7", "MISO", "output"),
         ("3", "RESERVED", "passive"), ("5", "RESERVED", "passive"), ("10", "RESERVED", "passive")],
        [("11", "INT1", "output"), ("9", "INT2", "bidirectional"), ("2", "NIC", "no_connect"),
         ("15", "NIC", "no_connect"), ("12", "GND", "power_in"), ("13", "GND", "passive"),
         ("16", "GND", "passive")])
    lsm = make_symbol(
        "LSM6DSO", "U", "Package_LGA:LGA-14_3x2.5mm_P0.5mm_LayoutBorder3x4y", "LSM6DSO 6-axis IMU, SPI/I2C",
        [("8", "VDD", "power_in"), ("5", "VDDIO", "power_in"), ("12", "CS", "input"),
         ("13", "SCL/SPC", "input"), ("14", "SDA/SDI", "bidirectional"), ("1", "SDO/SA0", "bidirectional"),
         ("2", "SDx", "bidirectional"), ("3", "SCx", "input")],
        [("4", "INT1", "output"), ("9", "INT2", "output"), ("10", "OCS_Aux", "output"),
         ("11", "SDO_Aux", "bidirectional"), ("6", "GND", "power_in"), ("7", "GND", "passive")])
    with open(os.path.join(OUT, "pmd.kicad_sym"), "w", encoding="utf-8") as f:
        f.write('(kicad_symbol_lib (version 20241209) (generator "pmd_generate") (generator_version "1.0")\n'
                + adxl + "\n" + lsm + "\n)\n")

    # ADXL372 land pattern: ADI datasheet Rev. C, Figure 111 (dims in mm).
    # Pins 1-5 left (top->bottom), 6-8 bottom (left->right), 9-13 right (bottom->top), 14-16 top (right->left).
    pads = []
    for k in range(5):
        pads.append((str(1 + k), -1.2875, -1.0 + 0.5 * k, 0.925, 0.3))
        pads.append((str(9 + k), 1.2875, 1.0 - 0.5 * k, 0.925, 0.3))
    for k in range(3):
        pads.append((str(6 + k), -0.5 + 0.5 * k, 1.275, 0.3, 0.8))
        pads.append((str(14 + k), 0.5 - 0.5 * k, -1.275, 0.3, 0.8))
    body = "\n".join(
        f'(pad "{n}" smd roundrect (at {x:.4f} {y:.4f}) (size {w} {h}) (layers "F.Cu" "F.Paste" "F.Mask") '
        f'(roundrect_rratio 0.15))' for n, x, y, w, h in sorted(pads, key=lambda p: int(p[0])))
    fp = f'''(footprint "ADI_LGA-16_3x3.25mm_P0.5mm" (version 20241229) (generator "pmd_generate") (layer "F.Cu")
(descr "ADI 16-terminal LGA 3 x 3.25 mm (ADXL372), land pattern per ADXL372 datasheet Rev. C Fig. 111")
(attr smd)
(property "Reference" "REF**" (at 0 -2.6 0) (layer "F.SilkS") (effects (font (size 0.8 0.8) (thickness 0.12))))
(property "Value" "ADXL372" (at 0 2.6 0) (layer "F.Fab") (effects (font (size 0.8 0.8) (thickness 0.12))))
(fp_rect (start -1.5 -1.625) (end 1.5 1.625) (stroke (width 0.1) (type solid)) (fill no) (layer "F.Fab"))
(fp_rect (start -2.0 -1.95) (end 2.0 1.95) (stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))
(fp_circle (center -2.05 -1.45) (end -1.95 -1.45) (stroke (width 0.2) (type solid)) (fill yes) (layer "F.SilkS"))
{body}
)
'''
    os.makedirs(os.path.join(OUT, "pmd.pretty"), exist_ok=True)
    with open(os.path.join(OUT, "pmd.pretty", "ADI_LGA-16_3x3.25mm_P0.5mm.kicad_mod"), "w", encoding="utf-8") as f:
        f.write(fp)

    with open(os.path.join(OUT, "sym-lib-table"), "w") as f:
        f.write('(sym_lib_table (version 7)\n  (lib (name "pmd")(type "KiCad")(uri "${KIPRJMOD}/pmd.kicad_sym")(options "")(descr "PMD tracker parts"))\n)\n')
    with open(os.path.join(OUT, "fp-lib-table"), "w") as f:
        f.write('(fp_lib_table (version 7)\n  (lib (name "pmd")(type "KiCad")(uri "${KIPRJMOD}/pmd.pretty")(options "")(descr "PMD tracker footprints"))\n)\n')


def write_project():
    tpl = os.path.join(KICAD, "demos", "royalblue54L_feather", "RoyalBlue54L-Feather.kicad_pro")
    d = json.load(open(tpl, encoding="utf-8"))
    base = dict(d["net_settings"]["classes"][0])
    classes = [dict(base, name="Default", track_width=DEFAULT_TRACK, clearance=CLEARANCE,
                    via_diameter=VIA_D, via_drill=VIA_DRILL)]
    patterns = []
    for i, (cname, (width, members)) in enumerate(NETCLASSES.items()):
        classes.append(dict(base, name=cname, track_width=width, clearance=CLEARANCE,
                            via_diameter=VIA_D, via_drill=VIA_DRILL, priority=i))
        patterns += [{"netclass": cname, "pattern": "/" + m} for m in members]  # root-sheet labels are /NAME
    d["net_settings"].update(classes=classes, netclass_assignments=None, netclass_patterns=patterns)
    # Rules sized for a standard 4-layer prototype service (e.g. JLCPCB 4L).
    d["board"]["design_settings"]["rules"].update(
        min_clearance=0.127, min_connection=0.1, min_track_width=0.127, min_via_diameter=0.45,
        min_through_hole_diameter=0.2, min_via_annular_width=0.1, min_hole_clearance=0.2,
        min_copper_edge_clearance=0.3)
    d["meta"]["filename"] = NAME + ".kicad_pro"
    d["sheets"] = [[ROOT_UUID, "Root"]]
    d["boards"] = []
    d["text_variables"] = {}
    d["libraries"] = {"pinned_footprint_libs": [], "pinned_symbol_libs": []}
    d.get("pcbnew", {}).pop("last_paths", None)
    d.get("schematic", {}).pop("last_opened_symbol_lib", None)
    with open(os.path.join(OUT, NAME + ".kicad_pro"), "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)


# ---------- schematic ----------

def fmt(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def label_angle(pin_angle):
    return {0: 180, 180: 0, 90: 270, 270: 90}[pin_angle]


def write_schematic():
    parts = dict(PARTS)
    for i, net in enumerate(PWR_FLAGS):
        parts[f"#FLG0{i + 1}"] = ("power:PWR_FLAG", "", "PWR_FLAG", {"1": net}, None)

    lib_ids = sorted({p[0] for p in parts.values()})
    syms = {lid: lib_symbol(lid) for lid in lib_ids}
    pinmaps = {lid: pins_of(t) for lid, t in syms.items()}

    # Shelf layout: big parts first, wrap at the sheet width. Labels extend ~20 mm past pins.
    order = sorted(parts, key=lambda r: (-len(pinmaps[parts[r][0]]), r))
    x, y, row_h, W = 25.4, 30.48, 0.0, 560.0
    items = []
    for ref in order:
        lid, fp, val, pinnets, _ = parts[ref]
        pm = pinmaps[lid]
        xs = [p[0] for p in pm.values()]
        ys = [p[1] for p in pm.values()]
        w = max(xs) - min(xs) + 50.8
        h = max(ys) - min(ys) + 30.48
        if x + w > W:
            x, y, row_h = 25.4, y + row_h, 0.0
        sx = round((x - min(xs) + 25.4) / 2.54) * 2.54
        sy = round((y + max(ys) + 12.7) / 2.54) * 2.54
        unknown = set(pinnets) - set(pm)
        assert not unknown, f"{ref}: pins {unknown} not on symbol {lid}"

        props = [("Reference", ref, sx, sy - max(ys) - 3.81, False),
                 ("Value", val, sx, sy - min(ys) + 3.81, False),
                 ("Footprint", fp, sx, sy, True), ("Datasheet", "", sx, sy, True)]
        if ref in MPN:
            props.append(("MPN", MPN[ref], sx, sy, True))
        prop_txt = "\n".join(
            f'(property "{k}" "{v}" (at {fmt(px)} {fmt(py)} 0)' + (" (hide yes)" if hid else "")
            + " (effects (font (size 1.27 1.27))))" for k, v, px, py, hid in props)
        pin_txt = "\n".join(f'(pin "{n}" (uuid "{uid(ref + "/pin/" + n)}"))' for n in pm)
        items.append(
            f'(symbol (lib_id "{lid}") (at {fmt(sx)} {fmt(sy)} 0) (unit 1) (exclude_from_sim no) (in_bom {"no" if ref.startswith("#") or "(in_bom no)" in syms[lid] else "yes"}) '
            f'(on_board {"no" if ref.startswith("#") else "yes"}) (dnp no) (uuid "{uid(ref)}")\n{prop_txt}\n{pin_txt}\n'
            f'(instances (project "{NAME}" (path "/{ROOT_UUID}" (reference "{ref}") (unit 1)))))')

        for n, (px, py, pa) in pm.items():
            ax, ay = sx + px, sy - py
            net = pinnets.get(n)
            if net:
                la = label_angle(pa)
                just = "left" if la in (0, 90) else "right"
                items.append(f'(label "{net}" (at {fmt(ax)} {fmt(ay)} {la}) '
                             f'(effects (font (size 1.27 1.27)) (justify {just} bottom)) (uuid "{uid(ref + "/lbl/" + n)}"))')
            else:
                items.append(f'(no_connect (at {fmt(ax)} {fmt(ay)}) (uuid "{uid(ref + "/nc/" + n)}"))')
        x += w
        row_h = max(row_h, h)

    sch = (f'(kicad_sch (version 20250610) (generator "eeschema") (generator_version "10.0") (uuid "{ROOT_UUID}") (paper "A2")\n'
           f'(title_block (title "PMD Tracker") (rev "A") (comment 1 "Generated from hardware/design.py"))\n'
           "(lib_symbols\n" + "\n".join(syms[l] for l in lib_ids) + "\n)\n"
           + "\n".join(items)
           + '\n(sheet_instances (path "/" (page "1")))\n(embedded_fonts no)\n)\n')
    with open(os.path.join(OUT, NAME + ".kicad_sch"), "w", encoding="utf-8") as f:
        f.write(sch)


# ---------- PCB ----------

def mm(x, y):
    import pcbnew
    return pcbnew.VECTOR2I_MM(OX + x, OY + y)


def outline(board):
    import pcbnew
    r, W, H = CORNER_R, BOARD_W, BOARD_H
    segs = [((r, 0), (W - r, 0)), ((W, r), (W, H - r)), ((W - r, H), (r, H)), ((0, H - r), (0, r))]
    for a, b in segs:
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(mm(*a)); s.SetEnd(mm(*b)); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(pcbnew.FromMM(0.1))
        board.Add(s)
    k = r * (1 - 2 ** -0.5)
    arcs = [((0, r), (k, k), (r, 0)), ((W - r, 0), (W - k, k), (W, r)),
            ((W, H - r), (W - k, H - k), (W - r, H)), ((r, H), (k, H - k), (0, H - r))]
    for a, m_, b in arcs:
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_ARC)
        s.SetArcGeometry(mm(*a), mm(*m_), mm(*b)); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(pcbnew.FromMM(0.1))
        board.Add(s)


def add_zone(board, layer, net, inset=0.4, priority=0):
    import pcbnew
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNet(net)
    z.SetAssignedPriority(priority)
    z.SetLocalClearance(pcbnew.FromMM(0.25))
    z.SetMinThickness(pcbnew.FromMM(0.2))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    ol = z.Outline()
    ol.NewOutline()
    for px, py in ((inset, inset), (BOARD_W - inset, inset), (BOARD_W - inset, BOARD_H - inset), (inset, BOARD_H - inset)):
        ol.Append(mm(px, py))
    board.Add(z)
    return z


def build_pcb():
    import pcbnew
    path = os.path.join(OUT, NAME + ".kicad_pcb")
    board = pcbnew.NewBoard(path)
    board.SetCopperLayerCount(4)
    ds = board.GetDesignSettings()
    ds.SetBoardThickness(pcbnew.FromMM(1.6))

    # Net names come from the schematic's own netlist, so board and schematic agree exactly
    # (including KiCad's "unconnected-(...)" names for no-connect pins).
    import xml.etree.ElementTree as ET
    pad_net, netinfo = {}, {}
    for n in ET.parse(os.path.join(OUT, "netlist.xml")).getroot().find("nets"):
        ni = pcbnew.NETINFO_ITEM(board, n.get("name"))
        board.Add(ni)
        netinfo[n.get("name").lstrip("/")] = ni
        for node in n:
            pad_net[(node.get("ref"), node.get("pin"))] = ni

    for ref, (lid, fpid, val, pinnets, (x, y, rot)) in PARTS.items():
        lib, name = fpid.split(":")
        libdir = os.path.join(OUT, "pmd.pretty") if lib == "pmd" else os.path.join(FP_DIR, lib + ".pretty")
        fp = pcbnew.FootprintLoad(libdir, name)
        assert fp, f"{ref}: footprint {fpid} not found"
        fp.SetReference(ref)
        fp.SetValue(val)
        fp.SetFPIDAsString(fpid)
        fp.SetPosition(mm(x, y))
        fp.SetOrientationDegrees(rot)
        fp.Reference().SetLayer(pcbnew.F_Fab)  # dense board: refs on the fab drawing, not silk
        board.Add(fp)
        if ref in MPN:
            fp.SetField("MPN", MPN[ref])
            fp.GetField("MPN").SetVisible(False)
        for pad in fp.Pads():
            ni = pad_net.get((ref, pad.GetNumber()))
            if ni:
                pad.SetNet(ni)

    outline(board)
    add_zone(board, pcbnew.In1_Cu, netinfo["GND"])
    add_zone(board, pcbnew.In2_Cu, netinfo["+3V3"])
    pcbnew.SaveBoard(path, board)


def export_dsn():
    import pcbnew
    path = os.path.join(OUT, NAME + ".kicad_pcb")
    board = pcbnew.LoadBoard(path)  # picks up netclasses from the .kicad_pro
    assert pcbnew.ExportSpecctraDSN(board, os.path.join(OUT, NAME + ".dsn"))


def finish():
    import pcbnew
    path = os.path.join(OUT, NAME + ".kicad_pcb")
    board = pcbnew.LoadBoard(path)
    assert pcbnew.ImportSpecctraSES(board, os.path.join(OUT, NAME + ".ses"))
    gnd = board.FindNet("/GND")
    add_zone(board, pcbnew.F_Cu, gnd)
    add_zone(board, pcbnew.B_Cu, gnd)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(path, board)


def check_netlist():
    """Schematic netlist (exported by kicad-cli) must equal design.py exactly."""
    import xml.etree.ElementTree as ET
    root = ET.parse(os.path.join(OUT, "netlist.xml")).getroot()
    got = {}
    for n in root.find("nets"):
        nodes = sorted((x.get("ref"), x.get("pin")) for x in n if not x.get("ref").startswith("#"))
        name = n.get("name").lstrip("/")
        if name.startswith(("unconnected-", "Net-(")):
            assert len(nodes) <= 1, (name, nodes)
            continue
        got[name] = nodes
    want = {k: sorted(v) for k, v in nets().items()}
    bad = [k for k in set(want) | set(got) if want.get(k) != got.get(k)]
    assert not bad, f"netlist mismatch: {bad}"
    print(f"netlist ok: {len(got)} nets")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    step = sys.argv[1]
    if step == "schematic":
        write_pmd_lib()
        write_project()
        write_schematic()
    elif step == "pcb":
        build_pcb()
        export_dsn()
    elif step == "check":
        check_netlist()
    elif step == "finish":
        finish()
