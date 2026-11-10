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

Settings are saved in the browser. **Copy settings** exports them as JSON.

## Run with Docker

```sh
docker compose up -d --build
```

Then open http://localhost:8080.

Without Compose:

```sh
docker build -t house-number-generator .
docker run -d -p 8080:80 --name house-number-generator --restart unless-stopped house-number-generator
```

## Run without Docker

Serve the `site/` folder with any static web server, for example:

```sh
cd site && python3 -m http.server 8080
```

## Notes

- three.js r128 is bundled in `site/vendor/`. Fonts load from Google Fonts, so the browser needs internet access for the lettering to show in the right typefaces.
- **Copy settings** uses the clipboard, which browsers only allow over HTTPS or on `localhost`. Anywhere else, the settings appear in a text box for you to copy by hand.
