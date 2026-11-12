#!/usr/bin/env python3
"""Serves the plaque designer and generates STL files on request.

  GET  /              the designer (site/)
  GET  /api/health    {"ok": true, "stl": true}
  POST /api/stl       settings JSON in, zip of the three STLs out
"""
import io
import json
import os
import pathlib
import re
import sys
import threading
import traceback
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent
SITE = ROOT / "site"
sys.path.insert(0, str(ROOT / "cad"))
import make_stl  # noqa: E402

PORT = int(os.environ.get("PORT", "8080"))
MAX_BODY = 32 * 1024
LOCK = threading.Lock()          # one build at a time keeps CPU use predictable

NUMBERS = {
    "W": (120, 500), "H": (80, 400), "D": (22, 80), "T": (1.5, 6), "edgeSize": (0, 5),
    "radius": (0, 80), "overhang": (0, 40), "F": (0.8, 3), "SW": (1.2, 4),
    "holeD": (3, 6), "holeInset": (8, 80), "track1": (-10, 40), "cap2": (5, 100),
    "track2": (-5, 30), "gap": (0, 120), "offY": (-80, 80), "divT": (0.8, 8),
    "divL": (10, 100), "w1": (100, 900), "w2": (100, 900),
}
CHOICES = {
    "align": ("baseline", "centre", "top"), "edge": ("square", "chamfer", "round"),
    "holeType": ("countersunk", "keyhole"), "holes": (2, 4),
}


def clean(raw):
    """Validate and clamp settings from the browser."""
    if not isinstance(raw, dict):
        raise ValueError("Settings must be a JSON object.")
    S = {}
    for k, (lo, hi) in NUMBERS.items():
        try:
            S[k] = min(hi, max(lo, float(raw[k])))
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Missing or invalid setting: {k}")
    for k, opts in CHOICES.items():
        v = raw.get(k)
        if v not in opts:
            raise ValueError(f"Invalid value for {k}: {v!r}")
        S[k] = v
    for k in ("f1", "f2"):
        if raw.get(k) not in make_stl.FONT_FILES:
            raise ValueError(f"Unknown font: {raw.get(k)!r}")
        S[k] = raw[k]
    S["line1"] = str(raw.get("line1", ""))[:8]
    S["line2"] = str(raw.get("line2", ""))[:32]
    if not (S["line1"].strip() or S["line2"].strip()):
        raise ValueError("Both lines of text are empty.")
    sizes = raw.get("sizes") or [60]
    S["sizes"] = [min(400.0, max(5.0, float(v))) for v in list(sizes)[:8]]
    S["divider"] = bool(raw.get("divider"))
    # layout options added later, so older saved settings without them still work
    for k in ("halign1", "halign2", "halignDiv"):
        S[k] = raw.get(k) if raw.get(k) in make_stl.HALIGNS else "centre"
    S["divStyle"] = raw.get("divStyle") if raw.get("divStyle") in make_stl.DIV_STYLES else "line"
    try:
        S["marginX"] = min(150.0, max(5.0, float(raw.get("marginX", 25))))
    except (TypeError, ValueError):
        raise ValueError("Invalid setting: marginX")
    S["front"] = "together" if raw.get("front") == "together" else "separate"
    try:
        S["recess"] = min(S["T"], max(0.0, float(raw.get("recess", 0))))
    except (TypeError, ValueError):
        raise ValueError("Missing or invalid setting: recess")
    S["pins"] = bool(raw.get("pins", True)) and S["front"] == "separate"
    S["seal"] = make_stl.seal_type(raw)
    return S


def front_notes(S):
    if S["front"] == "together":
        return [
            "Face plate and diffuser print together as one two-colour part, front-face down.",
            "  Import front_1_face_black.stl and front_2_diffuser_white.stl together and choose",
            "  to load them as one object with multiple parts. Then set part 1 to black and",
            "  part 2 to white. Use the same material for both (e.g. PETG + PETG) so they bond.",
            "  No bridges, no alignment pins, no glue.",
        ] + ([
            f"  Letters are recessed {S['recess']:g} mm. front_3_plugs_pla.stl fills the recesses while",
            "  printing: add it as a third part and give it PLA (or Bambu Support for PETG) on the",
            "  white nozzle. It only prints below the white, so there is one filament swap.",
            "  Load all three together so they keep their positions, and don't move the parts.",
            "  Pop the plugs out afterwards with a pick.",
        ] if S["recess"] > 0.05 else ["  Letters are flush white skins."])
    return [
        "face_plate.stl      black ASA/PETG, already front-face down",
        "diffuser_shell.stl  white PETG, already front-face down",
        ("Alignment: 3 pins on the face plate fit sockets in the diffuser (keyed, one way round)."
         if S["pins"] else "No alignment pins: line the face plate up by eye when gluing."),
    ]


def seal_note(S):
    loop, cut = make_stl.seal_length(S, make_stl.derive(S))
    if S["seal"] == "filament":
        return (f"Seal: 1.75 mm TPU filament (unprinted). Cut {cut:.0f} mm: 2% short of the "
                f"{loop:.0f} mm groove so it hugs the groove, plus {make_stl.ANCHOR_TAIL:.0f} mm at "
                "each end. Push each end through one of the two anchor holes at the bottom of the rim, "
                "fold the tail back and press it down into the slot above. Trim any spare.")
    return f"Seal: {loop / 1000:.2f} m of 2 mm silicone cord in the rim groove"


def slug(S):
    s = re.sub(r"[^a-z0-9]+", "-", (S["line1"] + " " + S["line2"]).lower()).strip("-")
    return (s or "plaque")[:60]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(SITE), **k)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def end_headers(self):
        if self.path in ("/", "/index.html"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _send(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/health":
            return self._send(200, b'{"ok": true, "stl": true}', "application/json")
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] != "/api/stl":
            return self._send(404, b"Not found", "text/plain")
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = 0
        if n <= 0 or n > MAX_BODY:
            return self._send(413, b"Settings are missing or too large.", "text/plain; charset=utf-8")
        try:
            S = clean(json.loads(self.rfile.read(n)))
        except (ValueError, json.JSONDecodeError) as e:
            return self._send(400, str(e).encode(), "text/plain; charset=utf-8")
        try:
            with LOCK:
                parts = make_stl.build(S)
        except Exception:
            traceback.print_exc()
            return self._send(500, b"The STL files could not be generated with these settings.", "text/plain; charset=utf-8")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, (_, data) in parts.items():
                z.writestr(name, data)
            z.writestr("settings.json", json.dumps(S, indent=2))
            z.writestr("README.txt", "\n".join([
                f"{S['line1']} {S['line2']}",
                f"Overall {S['W']:g} x {S['H']:g} x {S['D']:g} mm",
                "",
                *[make_stl.describe(name, m) for name, (m, _) in parts.items()],
                "",
                *front_notes(S),
                "back_panel.stl      any PETG/ASA, flat side down",
                "Three snap catches at the top click into notches in the back panel; the grub screw locks the bottom.",
                seal_note(S),
                "Hardware: M3 x 10 grub screw, M3 x 5.7 heat-set insert.",
            ]))
        name = slug(S) + "-stl.zip"
        self._send(200, buf.getvalue(), "application/zip",
                   {"Content-Disposition": f'attachment; filename="{name}"'})


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"House number generator on http://0.0.0.0:{PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
