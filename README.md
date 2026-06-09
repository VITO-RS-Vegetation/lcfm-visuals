# lcfm-visuals

Interactive globe visualizations and scripts for the LCFM project.

## Interactive globes

### LCM-10 MapLibre viewer

**`html/globe_maplibre.html`** — production MapLibre GL JS globe with the LCM-10 land cover layer over USGS imagery.

Live site (auto-deploys on push to `main`):

[https://vito-rs-vegetation.github.io/lcfm-visuals/#3.15/26.59/14.63](https://vito-rs-vegetation.github.io/lcfm-visuals/#3.15/26.59/14.63)

GitHack (per-commit preview, useful for testing before merging):

[https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/main/html/globe_maplibre.html](https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/main/html/globe_maplibre.html)

See [`plans/GLOBE_VIZ_PLAN.md`](plans/GLOBE_VIZ_PLAN.md) for implementation details and design decisions.

### LCM-10 CesiumJS viewer

**`html/globe_cesium.html`** — CesiumJS globe with the same LCM-10 land cover layer over USGS imagery, mirroring the MapLibre viewer.

Open directly in a browser via GitHack (no build step required):

[https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/main/html/globe_cesium.html](https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/main/html/globe_cesium.html)

> **Limitation:** the CesiumJS viewer does not use the WMTS endpoint for high zoom levels, so tile detail is capped at the base COG overview resolution.

See [`plans/GLOBE_VIZ_CESIUM.md`](plans/GLOBE_VIZ_CESIUM.md) for implementation details and design decisions.

> If either page appears stale after a new commit, use a commit-SHA URL to bypass the CDN cache:
> ```
> https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/<full-sha>/html/<filename>.html
> ```
> Get the SHA with `git rev-parse HEAD`.

---

## Plans

Reference documents, design decisions, and data specifications.

| File | Summary |
|---|---|
| [`plans/data.md`](plans/data.md) | Data sources reference: COG specs, asset URLs, colormap, and titiler tiling config for LCM-10, Blue Marble WMS, and Natural Earth country borders. |
| [`plans/GLOBE_VIZ_PLAN.md`](plans/GLOBE_VIZ_PLAN.md) | Implementation plan for the interactive rotatable globe built with MapLibre GL JS. |
| [`plans/GLOBE_VIZ_CESIUM.md`](plans/GLOBE_VIZ_CESIUM.md) | Implementation plan for the equivalent interactive 3D globe built with CesiumJS. |
| [`plans/lcm10_enhancements.md`](plans/lcm10_enhancements.md) | Planned enhancements to the LCM-10 visualisation layer (higher-resolution tiles, etc.). |

---

## Scripts

### Environment

All Python scripts are managed with [uv](https://docs.astral.sh/uv/). Install dependencies and create the virtual environment with:

```bash
uv sync
```

Prefix any script invocation with `uv run` to use the managed environment (no manual activation needed).

### `scripts/orthographic_globe.py` — static orthographic globe image (PNG)

Renders the LCM-10 land cover map across 1, 2, or 3 orthographic globe panels
side-by-side using Cartopy + Matplotlib and saves a single PNG.  Reads both
the LCM-10 and background imagery (world topo/bathy) directly from public
Cloud-Optimized GeoTIFFs over HTTPS — no local data files required.

Key config at the top of the script:

| Parameter | Default | Description |
|---|---|---|
| `N_GLOBES` | `2` | Number of panels (`1`, `2`, or `3`) |
| `GLOBE_CENTERS` | see script | `(lon, lat)` for each panel |
| `BACKGROUND` | `"black"` | `"black"`, `"white"`, or `"transparent"` |
| `DOWNSAMPLE_FACTOR` | `8` | COG overview level to read (must match an existing overview) |
| `DPI` | `300` | Output resolution |
| `COASTLINES` | `True` | Draw coastline outlines |
| `COUNTRY_BORDERS` | `False` | Draw country border lines |
| `BORDER_COLOR` | `"white"` | Shared colour for coastlines and country borders |
| `BORDER_WIDTH` | `0.4` | Shared line width for coastlines and country borders |
| `CUTLINE_LAT` | `None` | Latitude of horizontal cut; `None` = full circle. Everything below is clipped, producing a "cut figure" with a flat bottom edge. |

```bash
GDAL_HTTP_UNSAFESSL=YES python scripts/orthographic_globe.py
```

---

### `scripts/rotating_globe.py` — rotating globe animation (GIF + MP4)

Renders a full-rotation animation of the LCM-10 land cover layer draped on a
sphere using PyVista.  Outputs `globe_rotation_fps<N>.gif` and `.mp4`.

```bash
uv run python scripts/rotating_globe.py
```

---

### `scripts/flythrough_recorder.py` — MapLibre flythrough video (MP4)

Drives a headless MapLibre GL JS globe through a series of zoom/pan waypoints
and assembles the captured frames into an MP4 suitable for social media.
Uses Playwright (headless Chromium) for frame capture, with cosine ease-in-out
interpolation between waypoints and a 2× device pixel ratio so tiles are
fetched at HiDPI quality.

Flight paths are defined in [`configs/flightpath.toml`](configs/flightpath.toml).
Each `[[flightpath]]` entry specifies a name, output path, and a list of
`[[flightpath.waypoints]]` with `zoom`, `lat`, and `lon` values taken directly
from the `#zoom/lat/lon` URL fragment of the interactive viewer.

Key settings (in `[settings]` or overridden per entry):

| Parameter | Default | Description |
|---|---|---|
| `fps` | `30` | Output frame rate |
| `width` / `height` | `1080` | Output resolution in pixels |
| `duration_s` | `15.0` | Total flight duration (hold frames excluded) |
| `pre_frames` | `0` | Static hold frames on first waypoint before flight |
| `post_frames` | `0` | Static hold frames on last waypoint after flight |

**One-time setup** (after `uv sync`):

```bash
uv run playwright install chromium
```

```bash
# Quick test at low fps
uv run python scripts/flythrough_recorder.py \
    --config configs/flightpath.toml --name africa_zoom \
    --fps 10 --output images/test.mp4

# Full quality render
uv run python scripts/flythrough_recorder.py \
    --config configs/flightpath.toml --name africa_zoom

# Show browser window while recording (debug)
uv run python scripts/flythrough_recorder.py \
    --config configs/flightpath.toml --name africa_zoom --no-headless
```
