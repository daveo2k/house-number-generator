#!/usr/bin/env python3
"""Generate printable STL files for a house number plaque.

Reads the JSON from the designer's "Copy settings" button and writes three STLs:

  face_plate.stl     - lettering cut through, front edge profile, island bridges
  diffuser_shell.stl - white light box: front + sides, grub screw boss and insert hole. With
                       "edgeLight" it has two walls: an inner one round the sealed chamber that
                       backlights the letters, and an outer one that glows from a face-out LED
                       strip on the inner wall, in a channel left open to the house wall. The
                       insert then sits in the outer wall, in a slotted rib across the channel
  back_panel.stl     - wall plate with rim, seal groove, screw holes, cable hole, grub arm (with
                       an edge light: a tab out under the inner wall and a tongue in the rib slot)

With "front": "together" the face plate and diffuser print as one two-colour part instead:

  front_1_face_black.stl     - face plate, no bridges or pins
  front_2_diffuser_white.stl - diffuser shell plus a white skin in each letter
  front_3_plugs_pla.stl      - only with a letter recess: PLA plugs that fill the recesses
                               while printing, then pop out (PLA barely sticks to PETG)

They share one coordinate frame, so they load as one object with several parts.
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
from shapely.affinity import translate
from shapely.geometry import MultiPolygon, Point, Polygon, box as sbox
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
CLEAR = 0.45           # gap between back panel rim and shell inner wall, per side (0.2 was too snug with TPU)
BRIDGE_W = 1.2         # width of bridges holding letter islands
BRIDGE_T = 1.0         # thickness of bridges (on the back face of the plate)
INSERT_D = 4.0         # hole for M3 x 5.7 heat-set insert
INSERT_L = 5.7
GRUB_CLEAR_D = 3.4     # clearance hole below the insert for the grub screw and hex key
ARM_HOLE_D = 3.2       # hole in the back panel arm that the grub tip locks into
GRUB_Z = 15.0          # distance of the grub screw axis from the wall
BOSS_H = 6.0           # insert boss height, up from the shell's inside bottom face
ARM_GAP = 1.5          # gap between the boss and the back panel's grub arm (0.5 caught on a test print)
ARM_T = 3.0            # grub arm thickness
ARM_CHAMFER = 1.5      # lead-in on the arm tip's boss side, so it rides past the boss
# Rim groove per seal type: (width, depth, cord diameter). The shell gap is CLEAR, so a cord
# stands (d - depth) proud and is squeezed by (d - depth - CLEAR):
#   2 mm silicone cord:        0.35 mm squeeze (18%)
#   1.75 mm TPU filament:      0.2 mm squeeze (11%), width leaves room for it to spread
SEALS = {"cord": (2.2, 1.2, 2.0), "filament": (2.0, 1.1, 1.75)}
SEAL_Z = 6.0           # groove centre, measured from the wall
FILAMENT_STRETCH = 0.02   # cut the filament 2% short so it hugs the groove bottom
# TPU filament anchor: both ends of the filament poke through two holes in the bottom rim into a
# block inside, then fold back and press down into a pinch slot. It sits just left of the grub arm.
ANCHOR_X = -16.0       # centre between the two holes
ANCHOR_GAP = 4.0       # hole centre to centre
ANCHOR_HOLE = 3.0      # diamond hole, corner to corner (2.1 mm clear, no overhang past 45 degrees)
ANCHOR_FREE_W = 2.2    # lower channel the filament passes through freely
ANCHOR_PINCH_W = 1.5   # upper slot the folded tail is pressed into
ANCHOR_BLOCK_Y = 8.0   # block depth, in from the rim
ANCHOR_TOP = 11.0      # block top, from the wall
ANCHOR_TAIL = 25.0     # extra filament per end to go through and fold back
CABLE_D = 8.0
PIN_D, PIN_H, PIN_TIP = 3.0, 2.0, 0.4          # alignment pins on the back of the face plate
SOCKET_D, SOCKET_DEPTH = 3.3, 2.3              # matching sockets in the diffuser front
SOCKET_BOSS_D, SOCKET_BOSS_H = 7.0, 1.2        # thickens the diffuser wall behind each socket
RIM_H = 12.0           # back panel rim height along the top (seal groove low down, catch notches above it)
RIM_LOW_H = 7.0        # rim height on the sides and bottom, which have no catches (2 mm above the seal groove)
RIM_TOP_BAND = 10.0    # the full-height top rim runs this far down each side
LATCH_Z = 12.0         # catch position, measured from the wall
LATCH_ENGAGE = 1.4     # how far each catch hooks into its notch
LATCH_DEPTH = LATCH_ENGAGE + CLEAR   # how far each catch stands in from the shell's top wall
LATCH_NOTCH = LATCH_ENGAGE + 0.2     # notch depth into the rim, leaving the catch tip 0.2 mm clear
LATCH_PAD = 1.6        # thickens the back panel rim behind each notch, so the deeper notch keeps a 2 mm wall
LATCH_LEN = 18.0
# Edge light: a second, outer wall with a channel between it and the sealed chamber. A face-out
# COB strip on the inner wall lights the outer wall along its full depth, since nothing covers it.
EDGE_W_DEF = 20.0      # channel width, inner wall to outer wall
EDGE_GAP_DEF = 2.0     # outer wall stops this short of the house wall: rides over uneven walls, lets light bleed
EDGE_R_MIN = 5.0       # inner wall corner radius, so the strip isn't bent sharply
EDGE_MIN_CHAMBER = 90.0  # smallest chamber height left for the letters and back panel
EDGE_STRIP_W = 10.0    # strip width, for the drawings and parts note
EDGE_LEAD_D = 6.0      # hole through the inner wall for the strip's lead
EDGE_LEAD_X = 10.0     # beside the grub rib, where the strip's two ends meet (1 mm clear of the grub arm)
EDGE_RIB_W = 8.0       # rib across the channel that holds the insert and the back panel's tongue
EDGE_MIN_W = 10.0      # narrowest channel: room for the insert, tongue and clearances
# With an edge light the grub lock moves to the outer wall, so the screw is short and easy to reach:
# the insert is pressed into the outside of the rib, and a tongue on the back panel (on a tab that
# runs out under the inner wall, behind the seal) slides into a slot in the rib above it.
TONGUE_GAP = 0.5       # insert top to tongue
TONGUE_T = 4.0         # tongue thickness (along the grub screw)
TONGUE_W = 16.0        # tongue width: it prints upright, so the grub's pull runs across its layers;
                       # 16 wide leaves 6.4 mm of layer either side of the hole (strip gap is 20)
TONGUE_HOLE = 3.0      # blind hole in the tongue: the grub bottoms out in it
TONGUE_CHAMFER = 1.0   # lead-in on the tongue tip, both faces
TAB_W = 20.0           # tab from the back panel out to the tongue
BUTTRESS_OUT = 4.0     # 45 degree buttress on the tongue's outer face, up from the tab
BUTTRESS_IN = 7.0      # and on its inner face (less if the channel is narrow); both stay below the rib
TAB_T = 3.0            # tab thickness (the back panel's base)
LEAD_IN = 0.8          # chamfer on the shell's rear inner edge, eases it over the seal
SEG = 48               # segments for circles
HALIGNS = ("left", "centre", "right")
DIV_STYLES = ("line", "double", "dashed", "dotted", "tapered", "diamond")


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


def divider_shapes(x0, x1, yc, t, style):
    """Divider pieces between x0 and x1, centred on y = yc (Y up). Mirrors divPrims() in the page."""
    L, xc, out = x1 - x0, (x0 + x1) / 2, []
    bar = lambda a, b, dy=0.0: sbox(a, yc + dy - t / 2, b, yc + dy + t / 2)
    if style == "double":
        off = max(t, 1.2) / 2 + t / 2
        out += [bar(x0, x1, -off), bar(x0, x1, off)]
    elif style == "dashed":
        gap = max(2 * t, 3)
        n = max(1, round((L + gap) / (max(4 * t, 8) + gap)))
        dash = (L - (n - 1) * gap) / n
        out += [bar(x0 + i * (dash + gap), x0 + i * (dash + gap) + dash) for i in range(n)]
    elif style == "dotted":
        d = max(t, 1.5)
        n = max(1, math.floor((L - d) / (2.2 * d)) + 1)
        pitch = (L - d) / (n - 1) if n > 1 else 0
        out += [Point(x0 + d / 2 + i * pitch if n > 1 else xc, yc).buffer(d / 2, 16) for i in range(n)]
    elif style == "tapered":
        N = 48
        us = [-1 + 2 * i / N for i in range(N + 1)]
        top = [(xc + u * L / 2, yc + t / 2 * (1 - u * u)) for u in us]
        bot = [(xc + u * L / 2, yc - t / 2 * (1 - u * u)) for u in reversed(us[1:-1])]
        out.append(Polygon(top + bot).buffer(0))
    elif style == "diamond":
        r, gap = max(2 * t, 4), max(t, 1.5)
        out.append(Polygon([(xc - r, yc), (xc, yc + r), (xc + r, yc), (xc, yc - r)]))
        if xc - r - gap - x0 > 1:
            out += [bar(x0, xc - r - gap), bar(xc + r + gap, x1)]
    else:
        out.append(bar(x0, x1))
    return out


def lettering(S):
    """Return the lettering as shapely geometry in plate coordinates (mm, origin at centre, Y up).
    Mirrors the layout used by the web designer."""
    W, H = S["W"], S["H"]
    f1, f2 = Face(S["f1"], S["w1"]), Face(S["f2"], S["w2"])
    margin = S.get("marginX", 25)

    def place(glyphs, align):
        """Shift a line laid out from x = 0 by its ink (the letter shapes, not the font's spacing):
        centred on the plate, or with its edge on the side margin for left / right."""
        if not glyphs:
            return []
        minx, _, maxx, _ = unary_union(glyphs).bounds
        if align == "left":
            dx = -W / 2 + margin - minx
        elif align == "right":
            dx = W / 2 - margin - maxx
        else:
            dx = -(minx + maxx) / 2
        return [translate(g, dx, 0) for g in glyphs]

    chars = list(S["line1"].upper())
    t2 = list(S["line2"].upper())
    has1, has2 = any(c.strip() for c in chars), any(c.strip() for c in t2)
    sizes = S.get("sizes") or [60]
    caps = [(sizes[i] if i < len(sizes) and sizes[i] else (sizes[0] or 60)) for i in range(len(chars))]
    h1 = max([c for c, ch in zip(caps, chars) if ch.strip()] or [0])
    # a missing line takes no room, so one line on its own is centred top to bottom
    gap = S["gap"] if has1 and has2 else 0
    cap2 = S["cap2"] if has2 else 0
    top = (H - (h1 + gap + cap2)) / 2 + S.get("offY", 0)

    align = S.get("align", "baseline")
    x, line1 = 0.0, []
    for i, ch in enumerate(chars):
        base = top + caps[i] if align == "top" else top + (h1 + caps[i]) / 2 if align == "centre" else top + h1
        g = f1.glyph(ch, caps[i] / f1.cap, x, H / 2 - base)
        if g is not None and not g.is_empty:
            line1.append(g)
        x += f1.advance(ch, caps[i] / f1.cap) + S["track1"]
    shapes = place(line1, S.get("halign1", "centre"))

    if S.get("divider") and has1 and has2:
        L, yd, t = W * S["divL"] / 100, top + h1 + gap / 2, S["divT"]
        a = S.get("halignDiv", "centre")
        x0 = -W / 2 + margin if a == "left" else W / 2 - margin - L if a == "right" else -L / 2
        shapes += divider_shapes(x0, x0 + L, H / 2 - yd, t, S.get("divStyle", "line"))

    size2 = S["cap2"] / f2.cap
    base2 = top + h1 + gap + cap2
    x, line2 = 0.0, []
    for ch in t2:
        g = f2.glyph(ch, size2, x, H / 2 - base2)
        if g is not None and not g.is_empty:
            line2.append(g)
        x += f2.advance(ch, size2) + S["track2"]
    shapes += place(line2, S.get("halign2", "centre"))

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


def prism(pts_yz, x0, x1):
    """Convex prism along X from a (y, z) outline."""
    return mf.Manifold.hull_points([(x, y, z) for x in (x0, x1) for y, z in pts_yz])


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
    return (f"{name:28s} {b[3]-b[0]:6.1f} x {b[4]-b[1]:6.1f} x {b[5]-b[2]:5.1f} mm   "
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
    ch = edge_channel(S, Ws, Hs)
    # the sealed chamber: the whole shell, or the inner wall when there's an edge light channel
    if ch:
        Wc, Hc = Ws - 2 * (SW + ch), Hs - 2 * (SW + ch)
        Rc = max(EDGE_R_MIN, Rs - SW - ch)
    else:
        Wc, Hc, Rc = Ws, Hs, Rs
    Wp, Hp = Wc - 2 * SW - 2 * CLEAR, Hc - 2 * SW - 2 * CLEAR
    Rp = max(0.0, Rc - SW - CLEAR)
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
    gap = max(0.0, min(float(S.get("edgeGap", EDGE_GAP_DEF)), 5.0)) if ch else 0.0
    return dict(o=o, Ws=Ws, Hs=Hs, R=R, Rs=Rs, e=e, Wp=Wp, Hp=Hp, Rp=Rp, zDF=zDF,
                row_ys=row_ys, holes=holes, cable=cable, ch=ch, Wc=Wc, Hc=Hc, Rc=Rc, gap=gap)


def edge_channel(S, Ws, Hs):
    """Edge light channel width, 0 when off. Narrowed so the chamber keeps EDGE_MIN_CHAMBER."""
    if not S.get("edgeLight"):
        return 0.0
    w = min(float(S.get("edgeW", EDGE_W_DEF)), (min(Ws, Hs) - EDGE_MIN_CHAMBER) / 2 - S["SW"])
    return w if w >= EDGE_MIN_W else 0.0


def edge_strip(S, g):
    """Edge strip length round the inner wall (less the gap at the grub rib), and its centre depth."""
    if not g["ch"]:
        return 0.0, 0.0
    Wc, Hc, Rc = g["Wc"], g["Hc"], g["Rc"]
    length = 2 * (Wc + Hc) - (8 - 2 * math.pi) * Rc - 2 * EDGE_LEAD_X
    return length, g["zDF"] / 2


def tongue_y(g):
    """Edge light only: the back panel tongue's lower and upper faces (y), above the insert."""
    y = -g["Hs"] / 2 + INSERT_L + 0.3 + TONGUE_GAP
    return y, y + TONGUE_T


def buttresses(S, g):
    """Edge light only: sizes of the 45 degree buttresses on the tongue's outer and inner faces,
    kept clear of the outer wall and the inner wall."""
    t0, t1 = tongue_y(g)
    yo, yb = -g["Hs"] / 2, -g["Hc"] / 2
    return (max(0.0, min(BUTTRESS_OUT, t0 - (yo + S["SW"]) - 0.5)),
            max(0.0, min(BUTTRESS_IN, yb - t1 - CLEAR)))


def edge_lead_z(g):
    """Height of the strip lead hole: above the back panel's bottom rim, below the front."""
    return min(3 + RIM_LOW_H + 4, g["zDF"] - 3.5)


def pin_positions(S, g, letters):
    """Three alignment pins in three corners (keyed, so the plate only fits one way round),
    kept clear of the lettering and inside the diffuser front."""
    if not S.get("pins", True):
        return []
    inset = S["SW"] + 5 + g["Rs"] * 0.3
    x, y = g["Ws"] / 2 - inset, g["Hs"] / 2 - inset
    keep_out = letters.buffer(1.5)
    out = []
    for sx, sy in ((-1, 1), (1, 1), (-1, -1)):
        px = sx * x
        for _ in range(40):
            if not Point(px, sy * y).buffer(PIN_D / 2).intersects(keep_out):
                out.append((px, sy * y))
                break
            px -= sx * 3      # slide towards the centre until clear of the letters
    return out


# ---------------------------------------------------------------- parts
def together(S):
    """True when the face plate and diffuser print as one two-colour part."""
    return S.get("front") == "together"


def face_plate(S, g, letters, pins=(), with_bridges=True):
    W, H, T, e, R = S["W"], S["H"], S["T"], g["e"], g["R"]
    outline = rr(W, H, R)
    if e > 0.01:
        plate = ext(outline, T - e)
        # (inset, z) profile points from the plate edge to the front face
        if S.get("edge") == "round":
            # quarter round up to 45 degrees, then a straight 45 degree run to the front face,
            # so the edge never overhangs more than 45 degrees when printed face-down
            prof_pts = [(e * (1 - math.cos(a)), T - e + e * math.sin(a))
                        for a in (math.radians(45) * k / 6 for k in range(7))]
            i45, z45 = prof_pts[-1]
            prof_pts.append((i45 + (T - z45), T))
        else:
            prof_pts = [(0.0, T - e), (e, T)]
        slabs = []
        for inset, z in prof_pts:
            prof = outline.offset(-inset, mf.JoinType.Round, 2.0, SEG) if inset > 1e-4 else outline
            slabs.append(ext(prof, 0.001, max(T - e - 0.0005, min(z, T - 0.001))))
        plate = plate + mf.Manifold.batch_hull(slabs)
    else:
        plate = ext(outline, T)
    plate = plate - ext(to_cs(letters), T + 2, -1)
    br = bridges(letters) if with_bridges else None
    if br is not None and not br.is_empty:
        plate = plate + ext(to_cs(br), BRIDGE_T)
    for x, y in pins:   # pins stand off the back face (z < 0), with a chamfered tip
        plate = plate + cyl_z(x, y, -(PIN_H - PIN_TIP), 0.01, PIN_D)
        plate = plate + cyl_z(x, y, -PIN_H, -(PIN_H - PIN_TIP) + 0.001, PIN_D - 2 * PIN_TIP, PIN_D)
    return plate


def diffuser_shell(S, g, pins=()):
    SW, F, zDF = S["SW"], S["F"], g["zDF"]
    Ws, Hs, Rs = g["Ws"], g["Hs"], g["Rs"]
    Wc, Hc, Rc, ch = g["Wc"], g["Hc"], g["Rc"], g["ch"]
    yo = -Hs / 2                       # outer bottom face
    yb = -Hc / 2                       # chamber's outer bottom face (the same without an edge light)
    shell = ext(rr(Ws, Hs, Rs), zDF + F) - ext(rr(Ws - 2 * SW, Hs - 2 * SW, max(0, Rs - SW)), zDF + 1, -1)
    if ch:
        # inner wall round the sealed chamber, running back to the wall like the outer one
        shell = shell + ext(rr(Wc, Hc, Rc) - rr(Wc - 2 * SW, Hc - 2 * SW, max(0, Rc - SW)), zDF + 0.01)
        # rib across the channel at the bottom centre: holds the insert, pressed in from outside, and
        # ties the two walls together. It runs forward to the front, so it prints without support.
        shell = shell + box(-EDGE_RIB_W / 2, EDGE_RIB_W / 2, yo + SW - 0.01, yb + 0.01, GRUB_Z - 4, zDF + 0.01)
        shell = shell - cyl_y(0, GRUB_Z, yo - 1, yo + INSERT_L + 0.3, INSERT_D)
        # slot through the rib for the back panel's tongue, open towards the wall
        t0, t1 = tongue_y(g)
        tz = GRUB_Z + 4 + CLEAR
        shell = shell - box(-TONGUE_W / 2 - CLEAR, TONGUE_W / 2 + CLEAR, t0 - CLEAR, t1 + CLEAR, -1, tz)
        shell = shell - cyl_y(0, GRUB_Z, yo + INSERT_L, t0, GRUB_CLEAR_D)
        # notch in the inner wall's rear edge for the tongue's tab, below the seal
        shell = shell - box(-TAB_W / 2 - CLEAR, TAB_W / 2 + CLEAR, yb - 1, yb + SW + 1, -1, TAB_T + CLEAR)
        # hole beside the rib for the strip's lead, into the chamber
        shell = shell - cyl_y(EDGE_LEAD_X, edge_lead_z(g), yb - 1, yb + SW + 1, EDGE_LEAD_D)
        # weep holes in the outer wall: one under the chamber's weep hole, one at the other end
        for x in (-Wc / 2 + 15, Wc / 2 - 15):
            shell = shell - cyl_y(x, weep_z(S, g), yo - 1, yo + SW + 1, 2.0)
        # stop the outer wall short of the house wall (the inner wall still runs back to it)
        if g["gap"] > 0.01:
            # (the cut reaches 0.3 mm into the empty channel so the corners leave no slivers)
            shell = shell - ext(rr(Ws + 2, Hs + 2, Rs + 1) - rr(Ws - 2 * SW - 0.6, Hs - 2 * SW - 0.6, max(0, Rs - SW - 0.3)),
                                g["gap"] + 1, -1)
    if not ch:
        # boss for the insert, running forward to the front wall so it prints without support
        boss_top = yb + SW + BOSS_H
        shell = shell + box(-4, 4, yb + SW - 0.01, boss_top, GRUB_Z - 4, zDF + 0.01)
        shell = shell - cyl_y(0, GRUB_Z, yo - 1, boss_top + 1, GRUB_CLEAR_D)
        shell = shell - cyl_y(0, GRUB_Z, boss_top - INSERT_L - 0.3, boss_top + 1, INSERT_D)
    # weep hole near one bottom corner, towards the front so the back panel rim doesn't block it
    shell = shell - cyl_y(-Wc / 2 + 15, weep_z(S, g), yb - 1, yb + SW + 1, 2.0)
    # lead-in chamfer round the rear inner edge, so the shell slides over the seal
    inner = rr(Wc - 2 * SW, Hc - 2 * SW, max(0, Rc - SW))
    shell = shell - mf.Manifold.batch_hull([
        ext(inner.offset(LEAD_IN, mf.JoinType.Round, 2.0, SEG), 0.01, -0.01),
        ext(inner, 0.01, LEAD_IN)])
    # snap catches on the inside of the top wall. The front face is 45 degrees (prints without
    # support and holds firmly but releases with a firm pull); the rear face is a gentle ramp.
    y_in = Hc / 2 - SW
    d = LATCH_DEPTH
    ramp = d / math.tan(math.radians(30))
    for xc in latch_xs(g):
        shell = shell + prism([(y_in + 0.3, LATCH_Z + d + 0.3), (y_in - d, LATCH_Z),
                               (y_in + 0.3, LATCH_Z - ramp - 0.3)], xc - LATCH_LEN / 2, xc + LATCH_LEN / 2)
    # alignment sockets for the face plate pins, each backed by a small boss inside
    front = zDF + F
    for x, y in pins:
        shell = shell + cyl_z(x, y, zDF - SOCKET_BOSS_H, zDF + 0.01, SOCKET_BOSS_D)
        shell = shell - cyl_z(x, y, front - SOCKET_DEPTH, front + 1, SOCKET_D)
    return shell


def recess(S):
    """How far the letters sit back from the face in the two-colour front (0 = flush, T = through)."""
    return max(0.0, min(float(S.get("recess", 0)), S["T"]))


def letter_skin(S, g, letters):
    """For the two-colour front: a white skin in each letter, set back `recess` from the face and as
    thick as the diffuser front, so light passes through the same thickness of white as the separate
    parts. The diffuser front is cut away behind the skin to keep it that way.
    Returns (skin, pocket, plugs); plugs fill the recess in front of the skin, or None when flush."""
    D, F = S["D"], S["F"]
    r = recess(S)
    cs = to_cs(letters)
    skin_front = D - r
    skin_back = max(g["zDF"], skin_front - min(F, S["T"]))
    skin = ext(cs, skin_front - skin_back, skin_back)
    pocket = ext(cs, skin_back - g["zDF"] + 1, g["zDF"] - 1) if skin_back > g["zDF"] + 1e-6 else None
    plugs = ext(cs, r, skin_front) if r > 0.05 else None
    return skin, pocket, plugs


def flip_together(*parts):
    """Flip several parts face-down with one shared transform, so they stay registered."""
    parts = [m.rotate((180, 0, 0)) for m in parts]
    z0 = min(m.bounding_box()[2] for m in parts)
    return [m.translate((0, 0, -z0)) for m in parts]


def latch_xs(g):
    return (-g["Wp"] / 3, 0.0, g["Wp"] / 3)


def seal_type(S):
    """'cord' or 'filament'. Older settings saying 'gasket' (printed TPU) now mean filament."""
    return "filament" if S.get("seal") in ("filament", "gasket") else "cord"


def seal_length(S, g):
    """Length of the seal's centreline round the rim groove, and the length to cut, in mm."""
    w, depth, d = SEALS[seal_type(S)]
    inset = depth - d / 2                              # cord centre, in from the rim face
    W, H, R = g["Wp"] - 2 * inset, g["Hp"] - 2 * inset, max(0.0, g["Rp"] - inset)
    loop = 2 * (W + H) - (8 - 2 * math.pi) * R
    if seal_type(S) == "filament":
        cut = (loop - ANCHOR_GAP) * (1 - FILAMENT_STRETCH) + 2 * ANCHOR_TAIL
    else:
        cut = loop
    return loop, cut


def seal_groove_z(S):
    """Bottom of the seal groove, and the height where its 45 degree upper face starts at the
    groove bottom. The slope is set just clear of the seated cord (0.1 mm)."""
    w, depth, d = SEALS[seal_type(S)]
    zc, rc = SEAL_Z, depth - d / 2              # cord centre height, and its centre in from the rim face
    zt = zc + rc - depth + (d / 2 + 0.1) * math.sqrt(2)
    return zc - w / 2, max(zt, zc - w / 2 + 0.6)


def anchor_xs():
    return (ANCHOR_X - ANCHOR_GAP / 2, ANCHOR_X + ANCHOR_GAP / 2)


def weep_z(S, g):
    """Height of the weep hole from the wall: just behind the diffuser front, in the open space in
    front of the back panel's lowered bottom rim."""
    return max(3 + RIM_LOW_H + 1.5, g["zDF"] - 1.5)


def back_panel(S, g):
    SW, Hs = S["SW"], g["Hc"]
    Wp, Hp, Rp = g["Wp"], g["Hp"], g["Rp"]
    outer = rr(Wp, Hp, Rp)
    panel = ext(outer, 3)
    panel = panel + ext(outer - rr(Wp - 4, Hp - 4, max(0, Rp - 2)), RIM_H, 3)
    # lower the rim on the sides and bottom; only the top needs the height for the catch notches
    band = max(RIM_TOP_BAND, Rp + 4)
    panel = panel - box(-Wp / 2 - 1, Wp / 2 + 1, -Hp / 2 - 1, Hp / 2 - band, 3 + RIM_LOW_H, 3 + RIM_H + 1)
    if not g["ch"]:
        # notch in the bottom rim so it clears the shell's insert boss
        panel = panel - box(-5.5, 5.5, -Hp / 2 - 1, -Hp / 2 + 2.5, 9, 3 + RIM_H + 1)
    # notches in the top rim for the shell's catches. The upper face is 45 degrees (the face that
    # holds); the lower face follows the catch's 30 degree ramp so the catch seats fully. The tip
    # is 0.2 mm clear of the catch. A pad inside the rim keeps the wall behind each notch 2 mm thick.
    d = LATCH_NOTCH
    for xc in latch_xs(g):
        x0, x1 = xc - LATCH_LEN / 2 - 1, xc + LATCH_LEN / 2 + 1
        panel = panel + box(x0 - 2, x1 + 2, Hp / 2 - 2 - LATCH_PAD, Hp / 2 - 1.99, 2.99, 3 + RIM_H)
        panel = panel - prism([(Hp / 2 + 0.6, LATCH_Z - (d + 0.6) / math.tan(math.radians(30))),
                               (Hp / 2 - d, LATCH_Z), (Hp / 2 + 0.6, LATCH_Z + d + 0.6)], x0, x1)
    # seal groove round the outside of the rim. The panel prints flat side down, so the groove's
    # upper face is a 45 degree slope out to the rim face instead of a flat ceiling. The flat
    # lower face, which the shell pushes the seal against, is unchanged.
    zb, zt = seal_groove_z(S)
    sd = SEALS[seal_type(S)][1]
    bottom = rr(Wp - 2 * sd, Hp - 2 * sd, max(0, Rp - sd))
    core = ext(bottom, zt - zb + 0.01, zb) + mf.Manifold.batch_hull(
        [ext(bottom, 0.01, zt), ext(outer, 0.01, zt + sd - 0.01)])
    panel = panel - (ext(rr(Wp + 4, Hp + 4, Rp + 2), zt + sd - zb, zb) - core)
    if seal_type(S) == "filament":
        panel = seal_anchor(panel, Hp)
    az = GRUB_Z + 4
    if g["ch"]:
        # tab out under the inner wall, and a tongue standing up from it into the shell's rib slot.
        # The grub screw comes up from the insert below and bottoms out in the tongue's blind hole.
        t0, t1 = tongue_y(g)
        bo, bi = buttresses(S, g)
        panel = panel + box(-TAB_W / 2, TAB_W / 2, t0 - bo, -Hp / 2 + 1, 0, TAB_T)
        panel = panel + box(-TONGUE_W / 2, TONGUE_W / 2, t0, t1, 0, az)
        # 45 degree buttresses on both faces, so the tongue's lowest layers are much larger
        hw = TONGUE_W / 2
        if bo > 0.01:
            panel = panel + prism([(t0 - bo, TAB_T - 0.01), (t0 + 0.01, TAB_T - 0.01), (t0 + 0.01, TAB_T + bo)], -hw, hw)
        if bi > 0.01:
            panel = panel + prism([(t1 - 0.01, TAB_T - 0.01), (t1 + bi, TAB_T - 0.01), (t1 - 0.01, TAB_T + bi)], -hw, hw)
        panel = panel - cyl_y(0, GRUB_Z, t0 - 1, t0 + TONGUE_HOLE, ARM_HOLE_D)
        # 45 degree lead-in on both faces of the tip; they face up as printed
        c = TONGUE_CHAMFER
        panel = panel - prism([(t0 - 1, az + 1), (t0 - 1, az - c - 1), (t0 + c + 1, az + 1)], -hw - 1, hw + 1)
        panel = panel - prism([(t1 + 1, az + 1), (t1 + 1, az - c - 1), (t1 - c - 1, az + 1)], -hw - 1, hw + 1)
    else:
        # arm for the grub screw, tied into the bottom rim
        arm_y = -Hs / 2 + SW + BOSS_H + ARM_GAP + ARM_T / 2
        a0, a1 = arm_y - ARM_T / 2, arm_y + ARM_T / 2
        panel = panel + box(-6, 6, a0, a1, 2.99, az)
        panel = panel + box(-6, 6, -Hp / 2 + 1, a1, 2.99, 9)
        panel = panel - cyl_y(0, GRUB_Z, a0 - 1.5, a1 + 1.5, ARM_HOLE_D)
        # 45 degree chamfer on the tip's boss side; it faces up as printed, so no overhang
        panel = panel - prism([(a0 - 1, az + 1), (a0 - 1, az - ARM_CHAMFER - 1), (a0 + ARM_CHAMFER + 1, az + 1)], -7, 7)
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


def seal_anchor(panel, Hp):
    """Two holes through the bottom rim at the seal groove, into a block with a free channel
    behind each hole and a narrower pinch slot above it for the folded-back tail."""
    y_out, y_in = -Hp / 2, -Hp / 2 + 2
    y_end = y_in + ANCHOR_BLOCK_Y
    xa, xb = anchor_xs()
    half = ANCHOR_PINCH_W + 2.5
    panel = panel + box(xa - half, xb + half, y_in - 0.01, y_end, 2.99, ANCHOR_TOP)
    r = ANCHOR_HOLE / 2
    free_bot, free_top = SEAL_Z - r, SEAL_Z + r - 0.3
    for x in (xa, xb):
        # diamond hole along Y: a square turned 45 degrees in the XZ plane
        hole = mf.Manifold.hull_points([(x + dx, y, SEAL_Z + dz) for y in (y_out - 1, y_in + 0.5)
                                        for dx, dz in ((r, 0), (-r, 0), (0, r), (0, -r))])
        panel = panel - hole
        panel = panel - box(x - ANCHOR_FREE_W / 2, x + ANCHOR_FREE_W / 2, y_in - 0.01, y_end + 1, free_bot, free_top)
        panel = panel - box(x - ANCHOR_PINCH_W / 2, x + ANCHOR_PINCH_W / 2, y_in - 0.01, y_end + 1, free_top - 0.01, ANCHOR_TOP + 1)
    return panel


def build(S):
    """Build all parts. Returns {filename: (manifold, stl_bytes)}."""
    g = derive(S)
    letters = lettering(S)
    if together(S):
        plate = face_plate(S, g, letters, with_bridges=False).translate((0, 0, S["D"] - S["T"]))
        skin, pocket, plugs = letter_skin(S, g, letters)
        white = diffuser_shell(S, g)
        if pocket is not None:
            white = white - pocket
        white = white + skin
        flipped = flip_together(plate, white, *([plugs] if plugs is not None else []))
        parts = {"front_1_face_black.stl": flipped[0], "front_2_diffuser_white.stl": flipped[1]}
        if plugs is not None:
            parts["front_3_plugs_pla.stl"] = flipped[2]
    else:
        pins = pin_positions(S, g, letters)
        parts = {
            "face_plate.stl": flip_for_print(face_plate(S, g, letters, pins)),
            "diffuser_shell.stl": flip_for_print(diffuser_shell(S, g, pins)),
        }
    parts["back_panel.stl"] = back_panel(S, g)
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
