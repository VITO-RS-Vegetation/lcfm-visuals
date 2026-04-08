# lcfm_globe

PyVista-based tooling for the LCFM & SEN4LDN projects.

## Scripts

### `scripts/globe.py` — rotating globe animation (GIF + MP4)

Renders a full-rotation animation of the LCM-10 land cover layer draped on a
sphere using PyVista.  Outputs `globe_rotation_fps<N>.gif` and `.mp4`.

Dependencies: `pyvista rasterio imageio imageio-ffmpeg pillow`

### `scripts/build_globe_png_html.py` — simple interactive HTML globe

Generates `results/globe_interactive.html`: a self-contained (or URL-linked)
Three.js globe that can be opened directly in a browser.

> **Note:** this HTML is low quality — it uses a pre-rendered PNG texture and
> Three.js r128, which produces visible seam and projection artefacts.  It is
> a quick preview tool, not the target deliverable.  See `plans/GLOBE_VIZ_PLAN.md`
> for the production MapLibre GL JS implementation.
