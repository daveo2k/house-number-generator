# House Number Generator

A browser-based designer for backlit, 3D-printable house number plaques. You can rotate a live 3D preview and see a dimensioned front view, a cross-section, a back panel drawing and a parts list.

The plaque is a sealed light box with three printed parts:

1. **Face plate**: lettering cut through, with an optional chamfered or rounded front edge and rounded corners.
2. **Diffuser shell**: white. Forms the glowing sides and the panel behind the lettering. It can be inset so the face plate overhangs it.
3. **Back panel**: screws to the wall and carries the LED strip. It has a silicone cord seal and an arm that a recessed M3 grub screw, set in an M3 heat-set insert, locks into.

## Options

- Two lines of text, each with its own font and weight. There are 10 fonts.
- A separate height for each character on the top line, aligned by bottom, centre or top.
- Second line height and spacing, the gap between lines, and a divider line.
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
| `face_plate.stl` | Black ASA / PETG | Face-down, so the front is smooth and the chamfer prints as a 45° overhang |
| `diffuser_shell.stl` | White / natural PETG | Front-down, open side up, no supports |
| `back_panel.stl` | Any PETG / ASA | Flat side down |

```sh
python3 -m venv .venv
.venv/bin/pip install -r cad/requirements.txt
# paste the settings from the designer into design.json, then:
.venv/bin/python cad/make_stl.py design.json -o stl
```

Fonts are downloaded from the Google Fonts repository the first time each one is used, and cached in `cad/fonts/`.

Details built into the parts:
- The middles of letters such as A, O, R and D are held by 1.2 mm × 1 mm bridges on the back of the face plate.
- The insert hole is Ø4.0 mm, for an M3 × 5.7 heat-set insert, with a Ø3.4 mm hole below it for the grub screw and hex key.
- The rim groove is 2.2 × 1.2 mm, for 2 mm silicone cord.
- There's 0.2 mm clearance per side between the back panel and the shell, and a Ø2 mm weep hole in the bottom of the shell.

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
