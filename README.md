# lcfm_globe

Interactive globe visualizations and scripts for the LCFM & SEN4LDN projects.

## Interactive Globe — LCM-10 MapLibre viewer

**`html/globe_maplibre.html`** — production MapLibre GL JS globe with the LCM-10 land cover layer over USGS imagery.

Open directly in a browser via GitHack (no build step required):

[https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/main/html/globe_maplibre.html](https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/main/html/globe_maplibre.html)

> If the page appears stale after a new commit, use a commit-SHA URL to bypass the CDN cache:
> ```
> https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/<full-sha>/html/globe_maplibre.html
> ```
> Get the **full 40-character SHA** with `git rev-parse --verify HEAD` (do not use `--short`).

See [`plans/GLOBE_VIZ_PLAN.md`](plans/GLOBE_VIZ_PLAN.md) for implementation details and design decisions.

## Interactive Globe — LCM-10 CesiumJS viewer

**`html/globe_cesium.html`** — CesiumJS globe with the same LCM-10 land cover layer over USGS imagery, mirroring the MapLibre viewer.

Open directly in a browser via GitHack (no build step required):

[https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/main/html/globe_cesium.html](https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/main/html/globe_cesium.html)

> If the page appears stale after a new commit, use a commit-SHA URL to bypass the CDN cache:
> ```
> https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/<full-sha>/html/globe_cesium.html
> ```
> Get the **full 40-character SHA** with `git rev-parse --verify HEAD` (do not use `--short`).

See [`plans/GLOBE_VIZ_CESIUM.md`](plans/GLOBE_VIZ_CESIUM.md) for implementation details and design decisions.

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

Dependencies: `cartopy rasterio matplotlib numpy scipy`

---

### `scripts/rotating_globe.py` — rotating globe animation (GIF + MP4)

Renders a full-rotation animation of the LCM-10 land cover layer draped on a
sphere using PyVista.  Outputs `globe_rotation_fps<N>.gif` and `.mp4`.

Dependencies: `pyvista rasterio imageio imageio-ffmpeg pillow`
