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

### `scripts/rotating_globe.py` — multi-annual rotating globe (MP4)

Renders the annual LCM-10 maps (2020–2024) on a rotating PyVista globe.  The
globe makes one full 360° turn per year, then crossfades to the next year
without pausing the rotation; 2024 fades back into 2020 so the video loops
seamlessly.  It shows a large year label and a 2020–2024 timeline.

Textures are the precomputed DEM-shaded PNGs in `input/` (8000×4000 by
default).  The globe is rendered unlit because the relief is already baked
into the imagery; a mild limb darkening, star background and atmosphere glow
add depth.  All settings live in [`configs/rotating_globe.toml`](configs/rotating_globe.toml).

```bash
# Both renders in the config (0.4 turns per year) → images/rotating_globe_lcm10_2020_2024_2turns*.mp4
uv run python scripts/rotating_globe.py --config configs/rotating_globe.toml

# Fast check: one turn centred on the 2020 → 2021 change → *_transition.mp4
uv run python scripts/rotating_globe.py --name lcm10_2020_2024_2turns --only-transition
```

`turns_per_year` decouples year changes from the rotation: `0.4` gives 2 whole
turns for 5 years (30 s, preferred), `0.6` gives 3 turns; both loop seamlessly.
`0.5` gives 2.5 turns, which can't loop (`loop = false`).

The multidirectional render also enables two unlabelled Sentinel-2A/B
satellites, 180 degrees apart, with no orbit ring. Each is a simplified 3-D
model (gold-foil bus, nadir-pointing MSI instrument, three-panel solar wing)
that is lit, projected through the globe camera and rasterised in the 2-D
compositing step, so it is hidden pixel-exactly when it passes behind Earth.
The orbit uses the nominal 786 km altitude, 98.62 degree inclination and
10:30 local time at the descending node (with the Sun assumed behind the
viewer, so the southbound equator crossing is 22.5 degrees west of the disc
centre), but
the models are enlarged and `orbits_per_turn = 2.0` deliberately slows the
motion. This is illustrative, not an ephemeris or acquisition/coverage
simulation (swaths include oceans).
The 290 km swaths fade over `swath_trail_s = 2.0` seconds and move with the
Earth after each pass. Set `show_swath = false` for satellites alone, or
`satellites = false` to restore the original globe. `satellite_size_px`
is the on-screen length of the model including its solar wing. Whole Earth
turns and whole satellite orbits are both needed for a seamless loop,
including the trails.

```bash
uv run python scripts/rotating_globe.py --name lcm10_2020_2024_2turns_multidirectional
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
