# lcfm_globe

PyVista-based tooling for the LCFM & SEN4LDN projects.

## Interactive Globe — LCM-10 MapLibre viewer

**`html/globe_maplibre.html`** — production MapLibre GL JS globe with the LCM-10 land cover layer over USGS imagery.

Open directly in a browser via GitHack (no build step required):

[https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/main/html/globe_maplibre.html](https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/main/html/globe_maplibre.html)

> If the page appears stale after a new commit, use a commit-SHA URL to bypass the CDN cache:
> ```
> https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/<full-sha>/html/globe_maplibre.html
> ```
> Get the SHA with `git rev-parse HEAD`.

See `plans/GLOBE_VIZ_PLAN.md` for implementation details and design decisions.

## Interactive Globe — LCM-10 CesiumJS viewer

**`html/globe_cesium.html`** — CesiumJS globe with the same LCM-10 land cover layer over USGS imagery, mirroring the MapLibre viewer.

Open directly in a browser via GitHack (no build step required):

[https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/main/html/globe_cesium.html](https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/main/html/globe_cesium.html)

> If the page appears stale after a new commit, use a commit-SHA URL to bypass the CDN cache:
> ```
> https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/<full-sha>/html/globe_cesium.html
> ```
> Get the SHA with `git rev-parse HEAD`.

See `plans/GLOBE_VIZ_CESIUM.md` for implementation details and design decisions.

---

## Scripts

### `scripts/globe_ortho.py` — static orthographic globe image (PNG)

Renders the LCM-10 land cover map across 2 or 3 orthographic globe panels
side-by-side using Cartopy + Matplotlib and saves a single PNG.  Reads both
the LCM-10 and background imagery (world topo/bathy) directly from public
Cloud-Optimized GeoTIFFs over HTTPS — no local data files required.

Key config at the top of the script:

| Parameter | Default | Description |
|---|---|---|
| `N_GLOBES` | `2` | Number of panels (`2` or `3`) |
| `GLOBE_CENTERS` | see script | `(lon, lat)` for each panel |
| `BACKGROUND` | `"black"` | `"black"`, `"white"`, or `"transparent"` |
| `DOWNSAMPLE_FACTOR` | `8` | COG overview level to read (must match an existing overview) |
| `DPI` | `300` | Output resolution |

```bash
GDAL_HTTP_UNSAFESSL=YES python scripts/globe_ortho.py
```

Dependencies: `cartopy rasterio matplotlib numpy scipy`

---

### `scripts/globe.py` — rotating globe animation (GIF + MP4)

Renders a full-rotation animation of the LCM-10 land cover layer draped on a
sphere using PyVista.  Outputs `globe_rotation_fps<N>.gif` and `.mp4`.

Dependencies: `pyvista rasterio imageio imageio-ffmpeg pillow`
