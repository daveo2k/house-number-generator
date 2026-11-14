# House Number Generator

A browser-based designer for backlit, 3D-printable house number plaques. You can rotate a live 3D preview and see a dimensioned front view, a cross-section, a back panel drawing and a parts list.

The plaque is a sealed light box with three printed parts:

1. **Face plate**: lettering cut through, with an optional chamfered or rounded front edge and rounded corners.
2. **Diffuser shell**: white. Forms the glowing sides and the panel behind the lettering. It can be inset so the face plate overhangs it.
3. **Back panel**: screws to the wall and carries the LED strip. It has a rim seal (2 mm silicone cord or a plain length of 1.75 mm TPU filament) and an arm that a recessed M3 grub screw, set in an M3 heat-set insert, locks into.

## Options

- Two lines of text, each with its own font and weight. There are 10 fonts.
- A separate height for each character on the top line, aligned by bottom, centre or top.
- Second line height and spacing, and the gap between lines. Leave the second line empty for a number on its own, centred both ways on the plate.
- Left, centre or right alignment for each line and the divider, with a side margin for left and right.
- A divider between the lines: plain, double, dashed, dotted, tapered, or a line with a centre diamond.
- Overall width, height and depth.
- Face plate thickness, corner radius, and front edge (square, chamfer or rounded) with its size.
- Diffuser front and side thickness, and how far the face plate overhangs the diffuser.
- Wall fixing: 2 or 4 holes, countersunk or keyhole, screw size and distance from the edge.
- Night or day lighting, and an assembled or exploded view.

Settings are saved in the browser. **Download STL files** builds the three parts on the server and downloads them as a zip. **Copy settings** exports the design as JSON.

## Generate STL files

`cad/make_stl.py` turns the JSON from **Copy settings** into three print-ready STLs, using the same layout as the designer:

| File | Print in | Orientation |
|---|---|---|
| `face_plate.stl` | Black ASA / PETG | Face-down for the best front finish. The chamfer prints as a 45° overhang. The rounded edge finishes with a 45° bevel at the front face, so neither option needs supports. Alignment pins and letter bridges are on the rear, so they print last |
| `diffuser_shell.stl` | White / natural PETG | Front-down, open side up, no supports. The alignment sockets open on the bed side |
| `back_panel.stl` | Any PETG / ASA | Flat side down |
| `front_1_face_black.stl` + `front_2_diffuser_white.stl` (+ `front_3_plugs_pla.stl`) | Two colours, same material | Only when **Face plate and diffuser** is set to **Printed together**. These replace the two files above. Import both at once and load them as one object with two parts, then pick a filament for each part. Face-down, no supports |

```sh
python3 -m venv .venv
.venv/bin/pip install -r cad/requirements.txt
# paste the settings from the designer into design.json, then:
.venv/bin/python cad/make_stl.py design.json -o stl
```

Fonts are downloaded from the Google Fonts repository the first time each one is used, and cached in `cad/fonts/`.

Details built into the parts:
- **Printed together** (two-colour printers such as the Bambu H2D): the face plate and diffuser print as one part. Each letter gets a flush white skin as thick as the diffuser front, and is hollow behind it. Light passes through the same thickness of white as with the separate parts. Letter islands sit on the diffuser, so there are no bridges, no alignment pins and no glue. Use the same material for both colours so the layers bond.
- **Letter recess** (printed together only, default 1.5 mm): the white skin sits this far back from the face, so the letters still read as cut out. Set it to 0 for flush letters, or to the plate thickness for the same depth as the separate version. Printed face-down, a recess can't be bridged cleanly, so `front_3_plugs_pla.stl` fills it while printing. Give it PLA (or Bambu Support for PETG) on the white nozzle. It only prints below the white, so there's one filament swap. The plugs pop out afterwards, because PLA barely sticks to PETG.
- The middles of letters such as A, O, R and D are held by 1.2 mm × 1 mm bridges on the back of the face plate.
- The insert hole is Ø4.0 mm, for an M3 × 5.7 heat-set insert, with a Ø3.4 mm hole below it for the grub screw and hex key.
- With the edge light, the lock moves to the outer wall so the screw is short and easy to reach. The insert is pressed into the outside of the rib that crosses the channel at the bottom centre. A 3 mm × 20 mm tab on the back panel runs out under the inner wall (through a notch below the seal) to a 16 × 4 mm tongue, which slides into a slot in the rib as the shell goes on. The tongue prints upright, so the grub's pull runs across its layers: it's wide (6.4 mm of layer either side of the hole) and has 45° buttresses on both faces at its base. Use an M3 × 6 grub: wind it in flush before fitting the shell, then tighten it about 3.5 mm until it bottoms in the tongue's blind hole. The channel must be at least 10 mm wide.
- The rim groove is 2.2 × 1.2 mm for 2 mm silicone cord, or 2.0 × 1.1 mm for 1.75 mm TPU filament. Both cords are squeezed about 25–30% by the shell. The back panel prints flat side down, so the groove's upper face slopes out to the rim face at 45° instead of being a flat ceiling. It prints without supports and stays just clear of the seated cord.
- There's 0.2 mm clearance per side between the back panel and the shell, and a Ø2 mm weep hole in the bottom of the shell.
- Three Ø3 × 2 mm alignment pins on the back of the face plate fit Ø3.3 × 2.3 mm sockets in the diffuser front, so the two line up exactly for gluing. The pins are in three corners, so the plate only fits one way round. They move inwards automatically if lettering is in the way.
- Three snap catches inside the top of the shell click into notches in the back panel's 12 mm rim, with 1.4 mm of engagement. Each catch has a 45° front face and a 30° lead-in ramp, and each notch matches that shape, so it prints without supports and comes apart with a firm pull. The rim is thickened behind each notch. A 0.8 mm lead-in chamfer on the shell's rear edge helps it slide over the seal.
- The TPU filament seal is a plain length of 1.75 mm TPU, not printed. Cut it 2% shorter than the groove so it hugs the groove when stretched on (the designer and the zip's README give the length). Both ends go through two Ø2.1 mm holes in the bottom of the rim, just left of the grub arm, into an anchor block inside. Each end passes through a free channel. Fold the tail back and press it down into the 1.5 mm pinch slot above, so no glue is needed. The cut length includes 25 mm at each end for this. The joint is at the bottom, where water can't run into it. It stands 0.65 mm proud of the rim, so the shell squeezes it by about 0.45 mm.

## Run with Docker

```sh
docker compose up -d --build
```

Then open http://localhost:8080.

To use a different port, set `HTTP_PORT`, either in a `.env` file next to `docker-compose.yml` (see `.env.example`) or on the command line:

```sh
HTTP_PORT=9000 docker compose up -d --build
```

## Deploy with Portainer

1. In Portainer, go to **Stacks → Add stack** and choose **Repository**.
2. Repository URL: `https://github.com/daveo2k/house-number-generator`
3. Repository reference: `refs/heads/main`
4. Compose path: `docker-compose.yml`
5. Under **Environment variables**, add `HTTP_PORT` set to the port you want. If you leave it out, it uses 8080.
6. Click **Deploy the stack**.

Portainer builds the image from the Dockerfile on the host. It's never pulled from a registry, because the compose file sets `pull_policy: build`. To pick up changes later, open the stack and click **Pull and redeploy**. That fetches the latest code from GitHub and rebuilds the image. You can also turn on **GitOps updates** so Portainer redeploys automatically when the repo changes.

Without Compose:

```sh
docker build -t house-number-generator .
docker run -d -p 8080:80 --name house-number-generator --restart unless-stopped house-number-generator
```

## Run without Docker

```sh
python3 -m venv .venv
.venv/bin/pip install -r cad/requirements.txt
PORT=8080 .venv/bin/python server.py
```

`server.py` serves the page from `site/` and adds two endpoints: `GET /api/health`, and `POST /api/stl`, which takes the settings JSON and returns a zip. If you serve `site/` with a plain static web server instead, the designer still works but the **Download STL files** button stays hidden.

## Notes

- The container runs Python, not nginx, and listens on port 8080 inside the container. Fonts for STL generation are downloaded into the image when it's built, so generating works offline. The page itself still loads its fonts from Google Fonts, so the browser needs internet access for the preview lettering to show in the right typefaces.
- three.js r128 is bundled in `site/vendor/`.
- **Copy settings** uses the clipboard, which browsers only allow over HTTPS or on `localhost`. Anywhere else, the settings appear in a text box for you to copy by hand.
