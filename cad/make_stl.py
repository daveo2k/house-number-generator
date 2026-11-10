#!/usr/bin/env python3
"""Generate printable STL files for a house number plaque.

Reads the JSON from the designer's "Copy settings" button and writes three STLs:

  face_plate.stl     - lettering cut through, front edge profile, island bridges
  diffuser_shell.stl - white light box: front + sides, grub screw boss and insert hole
  back_panel.stl     - wall plate with rim, seal groove, screw holes, cable hole, grub arm

Each part is placed ready to print (largest flat face on the bed).

Usage:
  python3 make_stl.py design.json [-o output_dir]
"""
import argparse
import json
import math
import pathlib
import urllib.request

import manifold3d as mf
import numpy as np
import trimesh
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from shapely.geometry import MultiPolygon, Polygon, box as sbox
from shapely.ops import unary_union

HERE = pathlib.Path(__file__).resolve().parent
FONT_DIR = HERE / "fonts"
GF = "https://github.com/google/fonts/raw/main/"
FONT_FILES = {
    "Jost": "ofl/jost/Jost[wght].ttf",
    "Montserrat": "ofl/montserrat/Montserrat[wght].ttf",
    "Outfit": "ofl/outfit/Outfit[wght].ttf",
    "Josefin Sans": "ofl/josefinsans/JosefinSans[wght].ttf",
    "Oswald": "ofl/oswald/Oswald[wght].ttf",
    "Bebas Neue": "ofl/bebasneue/BebasNeue-Regular.ttf",
    "Roboto Slab": "apache/robotoslab/RobotoSlab[wght].ttf",
    "Playfair Display": "ofl/playfairdisplay/PlayfairDisplay[wght].ttf",
    "DM Serif Display": "ofl/dmserifdisplay/DMSerifDisplay-Regular.ttf",
    "Cinzel": "ofl/cinzel/Cinzel[wght].ttf",
}

# Hardware and fit constants (mm)
CLEAR = 0.2            # gap between back panel rim and shell inner wall, per side
BRIDGE_W = 1.2         # width of bridges holding letter islands
BRIDGE_T = 1.0         # thickness of bridges (on the back face of the plate)
INSERT_D = 4.0         # hole for M3 x 5.7 heat-set insert
INSERT_L = 5.7
GRUB_CLEAR_D = 3.4     # clearance hole below the insert for the grub screw and hex key
ARM_HOLE_D = 3.2       # hole in the back panel arm that the grub tip locks into
GRUB_Z = 15.0          # distance of the grub screw axis from the wall
SEAL_W, SEAL_DEPTH = 2.2, 1.2   # groove for 2 mm silicone cord
CABLE_D = 8.0
SEG = 48               # segments for circles


# ---------------------------------------------------------------- fonts / text
def font_file(family):
    """Path to the font file, downloading it from the Google Fonts repository if needed."""
    rel = FONT_FILES.get(family)
    if not rel:
        raise ValueError(f"Unknown font: {family}")
    path = FONT_DIR / pathlib.Path(rel).name
    if not path.exists():
        FONT_DIR.mkdir(parents=True, exist_ok=True)
        url = GF + rel.replace("[", "%5B").replace("]", "%5D")
        print(f"Downloading {family} ...")
        urllib.request.urlretrieve(url, path)
    return path


def load_font(family, weight):
    font = TTFont(font_file(family))
    if "fvar" in font:
        axis = next(a for a in font["fvar"].axes if a.axisTag == "wght")
        w = max(axis.minValue, min(axis.maxValue, weight))
        font = instantiateVariableFont(font, {"wght": w})
    return font


class FlatPen(BasePen):
    """Collects glyph outlines as flattened point lists."""

    def __init__(self, glyphset, steps=10):
        super().__init__(glyphset)
        self.contours, self.cur, self.steps = [], [], steps

    def _moveTo(self, p):
        self.cur = [p]

    def _lineTo(self, p):
        self.cur.append(p)

    def _curveToOne(self, p1, p2, p3):
        p0 = self.cur[-1]
        for i in range(1, self.steps + 1):
            t = i / self.steps
            a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
            self.cur.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                             a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))

    def _qCurveToOne(self, p1, p2):
        p0 = self.cur[-1]
        for i in range(1, self.steps + 1):
            t = i / self.steps
            a, b, c = (1 - t) ** 2, 2 * (1 - t) * t, t ** 2
            self.cur.append((a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1]))

    def _closePath(self):
        if len(self.cur) > 2:
            self.contours.append(self.cur)
        self.cur = []

    _endPath = _closePath


class Face:
    def __init__(self, family, weight):
        self.font = load_font(family, weight)
        self.upm = self.font["head"].unitsPerEm
        self.cmap = self.font.getBestCmap()
        self.gs = self.font.getGlyphSet()
        self.cache = {}
        h = self.outline("H")[0]
        self.cap = max(y for c in h for _, y in c) / self.upm   # cap height as a fraction of the em

    def outline(self, ch):
        if ch not in self.cache:
            name = self.cmap.get(ord(ch))
            if name is None:
                self.cache[ch] = ([], 0)
            else:
                pen = FlatPen(self.gs)
                self.gs[name].draw(pen)
                self.cache[ch] = (pen.contours, self.font["hmtx"][name][0])
        return self.cache[ch]

    def advance(self, ch, size):
        return self.outline(ch)[1] * size / self.upm

    def glyph(self, ch, size, ox, oy):
        contours, _ = self.outline(ch)
        if not contours:
            return None
        s = size / self.upm
        # Variable fonts often draw strokes as overlapping contours, so resolve with the
        # non-zero winding rule first, then rebuild clean polygons (outer rings + holes).
        cs = mf.CrossSection([[(ox + x * s, oy + y * s) for x, y in c] for c in contours], mf.FillRule.NonZero)
        geom = None
        for c in cs.to_polygons():
            if len(c) < 3:
                continue
            p = Polygon(c).buffer(0)
            geom = p if geom is None else geom.symmetric_difference(p)
        return geom


def lettering(S):
    """Return the lettering as shapely geometry in plate coordinates (mm, origin at centre, Y up).
    Mirrors the layout used by the web designer."""
    W, H = S["W"], S["H"]
    f1, f2 = Face(S["f1"], S["w1"]), Face(S["f2"], S["w2"])
    shapes = []

    chars = list(S["line1"].upper())
    sizes = S.get("sizes") or [60]
    caps = [(sizes[i] if i < len(sizes) and sizes[i] else (sizes[0] or 60)) for i in range(len(chars))]
    h1 = max([c for c, ch in zip(caps, chars) if ch != " "] or [0])
    widths = [f1.advance(ch, caps[i] / f1.cap) for i, ch in enumerate(chars)]
    tot1 = sum(widths) + S["track1"] * max(0, len(chars) - 1)
    top = (H - (h1 + S["gap"] + S["cap2"])) / 2 + S.get("offY", 0)
    x = (W - tot1) / 2
    for i, ch in enumerate(chars):
        align = S.get("align", "baseline")
        base = top + caps[i] if align == "top" else top + (h1 + caps[i]) / 2 if align == "centre" else top + h1
        g = f1.glyph(ch, caps[i] / f1.cap, x - W / 2, H / 2 - base)
        if g is not None and not g.is_empty:
            shapes.append(g)
        x += widths[i] + S["track1"]

    if S.get("divider"):
        L, yd, t = W * S["divL"] / 100, top + h1 + S["gap"] / 2, S["divT"]
        shapes.append(sbox(-L / 2, H / 2 - yd - t / 2, L / 2, H / 2 - yd + t / 2))

    size2 = S["cap2"] / f2.cap
    t2 = list(S["line2"].upper())
    w2 = sum(f2.advance(c, size2) for c in t2) + S["track2"] * max(0, len(t2) - 1)
    base2 = top + h1 + S["gap"] + S["cap2"]
    x = (W - w2) / 2
    for ch in t2:
        g = f2.glyph(ch, size2, x - W / 2, H / 2 - base2)
        if g is not None and not g.is_empty:
            shapes.append(g)
        x += f2.advance(ch, size2) + S["track2"]

    return unary_union(shapes)


def bridges(letters):
    """Thin vertical strips that tie each letter island (the middle of A, O, R...) to the plate."""
    out = []
    polys = letters.geoms if isinstance(letters, MultiPolygon) else [letters]
    for poly in polys:
        for ring in poly.interiors:
            hole = Polygon(ring)
            cx = hole.representative_point().x
            _, miny, _, maxy = poly.bounds
            strip = sbox(cx - BRIDGE_W / 2, miny - 1, cx + BRIDGE_W / 2, maxy + 1)
            out.append(strip.intersection(poly))
    return unary_union(out) if out else None


# ---------------------------------------------------------------- geometry helpers
def to_cs(geom):
    contours = []
    polys = geom.geoms if hasattr(geom, "geoms") else [geom]
    for p in polys:
        if p.is_empty or not isinstance(p, Polygon):
            continue
        contours.append(list(p.exterior.coords)[:-1])
        contours.extend(list(r.coords)[:-1] for r in p.interiors)
    return mf.CrossSection(contours, mf.FillRule.EvenOdd)


def rr(w, h, r):
    r = max(0.0, min(r, w / 2 - 0.01, h / 2 - 0.01))
    if r < 0.05:
        return mf.CrossSection.square((w, h), True)
    return mf.CrossSection.square((w - 2 * r, h - 2 * r), True).offset(r, mf.JoinType.Round, 2.0, SEG)


def ext(cs, h, z=0.0):
    return mf.Manifold.extrude(cs, h).translate((0, 0, z))


def box(x0, x1, y0, y1, z0, z1):
    return mf.Manifold.cube((x1 - x0, y1 - y0, z1 - z0)).translate((x0, y0, z0))


def cyl_y(x, z, y0, y1, d):
    """Cylinder along Y (vertical in the installed plaque)."""
    return mf.Manifold.cylinder(y1 - y0, d / 2, d / 2, SEG).rotate((-90, 0, 0)).translate((x, y0, z))


def cyl_z(x, y, z0, z1, d0, d1=None):
    return mf.Manifold.cylinder(z1 - z0, d0 / 2, (d1 if d1 is not None else d0) / 2, SEG).translate((x, y, z0))


def flip_for_print(m):
    """Turn a part front-side down on the bed (180 degrees about X), resting on z = 0."""
    m = m.rotate((180, 0, 0))
    return m.translate((0, 0, -m.bounding_box()[2]))


def stl_bytes(m):
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties)[:, :3]
    f = np.asarray(mesh.tri_verts)
    return trimesh.Trimesh(v, f, process=False).export(file_type="stl")


def describe(name, m):
    b = m.bounding_box()
    return (f"{name:20s} {b[3]-b[0]:6.1f} x {b[4]-b[1]:6.1f} x {b[5]-b[2]:5.1f} mm   "
            f"{m.volume()/1000:7.1f} cm3")


# ---------------------------------------------------------------- derived sizes (match the web designer)
def derive(S):
    W, H = S["W"], S["H"]
    o = max(0.0, min(S.get("overhang", 0), (min(W, H) - 60) / 2))
    Ws, Hs = W - 2 * o, H - 2 * o
    R = max(0.0, min(S.get("radius", 0), min(W, H) / 2 - 1))
    Rs = max(0.0, R - o)
    e = 0.0 if S.get("edge", "chamfer") == "square" else max(0.0, min(S.get("edgeSize", 0), S["T"] - 0.6))
    SW = S["SW"]
    Wp, Hp = Ws - 2 * SW - 2 * CLEAR, Hs - 2 * SW - 2 * CLEAR
    Rp = max(0.0, Rs - SW - CLEAR)
    zDF = S["D"] - S["T"] - S["F"]
    rows = max(2, round((Hp - 40) / 45))
    span = Hp / 2 - 30
    row_ys = [-span + 2 * span * i / (rows - 1) for i in range(rows)]
    i = S["holeInset"]
    hx, hy = Wp / 2 - i, Hp / 2 - i
    if S["holes"] == 4:
        holes = [(-hx, hy), (hx, hy), (-hx, -hy), (hx, -hy)]
    elif S["holeType"] == "keyhole":
        holes = [(-hx, hy), (hx, hy)]
    else:
        holes = [(-hx, 0), (hx, 0)]
    cable = (0.0, (row_ys[0] + row_ys[1]) / 2)
    return dict(o=o, Ws=Ws, Hs=Hs, R=R, Rs=Rs, e=e, Wp=Wp, Hp=Hp, Rp=Rp, zDF=zDF,
                row_ys=row_ys, holes=holes, cable=cable)


# ---------------------------------------------------------------- parts
def face_plate(S, g, letters):
    W, H, T, e, R = S["W"], S["H"], S["T"], g["e"], g["R"]
    outline = rr(W, H, R)
    if e > 0.01:
        plate = ext(outline, T - e)
        n = 8 if S.get("edge") == "round" else 1
        slabs = []
        for k in range(n + 1):
            a = (k / n) * math.pi / 2
            inset = e * (1 - math.cos(a)) if n > 1 else e * k
            z = T - e + (e * math.sin(a) if n > 1 else e * k)
            prof = outline.offset(-inset, mf.JoinType.Round, 2.0, SEG) if inset > 1e-4 else outline
            slabs.append(ext(prof, 0.001, min(z, T - 0.001) if k else z - 0.0005))
        plate = plate + mf.Manifold.batch_hull(slabs)
    else:
        plate = ext(outline, T)
    plate = plate - ext(to_cs(letters), T + 2, -1)
    br = bridges(letters)
    if br is not None and not br.is_empty:
        plate = plate + ext(to_cs(br), BRIDGE_T)
    return flip_for_print(plate)


def diffuser_shell(S, g):
    SW, F, zDF = S["SW"], S["F"], g["zDF"]
    Ws, Hs, Rs = g["Ws"], g["Hs"], g["Rs"]
    yb = -Hs / 2                       # outer bottom face
    shell = ext(rr(Ws, Hs, Rs), zDF + F) - ext(rr(Ws - 2 * SW, Hs - 2 * SW, max(0, Rs - SW)), zDF + 1, -1)
    # boss for the insert, running forward to the front wall so it prints without support
    boss_top = yb + SW + 6
    shell = shell + box(-4, 4, yb + SW - 0.01, boss_top, GRUB_Z - 4, zDF + 0.01)
    shell = shell - cyl_y(0, GRUB_Z, yb - 1, boss_top + 1, GRUB_CLEAR_D)
    shell = shell - cyl_y(0, GRUB_Z, boss_top - INSERT_L - 0.3, boss_top + 1, INSERT_D)
    # weep hole near one bottom corner
    shell = shell - cyl_y(-Ws / 2 + 15, 4, yb - 1, yb + SW + 1, 2.0)
    return flip_for_print(shell)


def back_panel(S, g):
    SW, Hs = S["SW"], g["Hs"]
    Wp, Hp, Rp = g["Wp"], g["Hp"], g["Rp"]
    outer = rr(Wp, Hp, Rp)
    panel = ext(outer, 3)
    panel = panel + ext(outer - rr(Wp - 4, Hp - 4, max(0, Rp - 2)), 6, 3)
    # seal groove round the outside of the rim
    groove = outer - rr(Wp - 2 * SEAL_DEPTH, Hp - 2 * SEAL_DEPTH, max(0, Rp - SEAL_DEPTH))
    panel = panel - ext(groove, SEAL_W, 6 - SEAL_W / 2)
    # arm for the grub screw, tied into the bottom rim
    arm_y = -Hs / 2 + SW + 8
    panel = panel + box(-6, 6, arm_y - 1.5, arm_y + 1.5, 2.99, GRUB_Z + 4)
    panel = panel + box(-6, 6, -Hp / 2 + 1, arm_y + 1.5, 2.99, 9)
    panel = panel - cyl_y(0, GRUB_Z, arm_y - 3, arm_y + 3, ARM_HOLE_D)
    # wall screw holes
    d = S["holeD"]
    for x, y in g["holes"]:
        if S["holeType"] == "keyhole":
            panel = panel - cyl_z(x, y, -1, 4, 2 * d + 1)
            panel = panel - box(x - (d + 0.5) / 2, x + (d + 0.5) / 2, y, y + 9, -1, 4)
            panel = panel - cyl_z(x, y + 9, -1, 4, d + 0.5)
        else:
            panel = panel - cyl_z(x, y, -1, 4, d + 0.5)
            head = 2 * d
            panel = panel - cyl_z(x, y, 3 - (head - d - 0.5) / 2, 3.01, d + 0.5, head)
    panel = panel - cyl_z(g["cable"][0], g["cable"][1], -1, 4, CABLE_D)
    return panel


def build(S):
    """Build all parts. Returns {filename: (manifold, stl_bytes)}."""
    g = derive(S)
    letters = lettering(S)
    parts = {
        "face_plate.stl": face_plate(S, g, letters),
        "diffuser_shell.stl": diffuser_shell(S, g),
        "back_panel.stl": back_panel(S, g),
    }
    return {name: (m, stl_bytes(m)) for name, m in parts.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("settings", help="JSON from the designer's Copy settings button")
    ap.add_argument("-o", "--out", default="stl", help="output folder (default: ./stl)")
    a = ap.parse_args()
    S = json.loads(pathlib.Path(a.settings).read_text())
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"Plaque {S['W']} x {S['H']} x {S['D']} mm")
    for name, (m, data) in build(S).items():
        (out / name).write_bytes(data)
        print("  " + describe(name, m))


if __name__ == "__main__":
    main()
