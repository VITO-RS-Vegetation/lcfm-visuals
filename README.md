# lcfm_globe

PyVista-based tooling for the LCFM & SEN4LDN projects.

## Interactive Globe — LCM-10 MapLibre viewer

**`html/globe_maplibre.html`** — production MapLibre GL JS globe with the LCM-10 land cover layer over USGS imagery.

Open directly in a browser via GitHack (no build step required):

```
https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/main/html/globe_maplibre.html
```

> If the page appears stale after a new commit, use a commit-SHA URL to bypass the CDN cache:
> ```
> https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/<full-sha>/html/globe_maplibre.html
> ```
> Get the SHA with `git rev-parse HEAD`.

See `plans/GLOBE_VIZ_PLAN.md` for implementation details and design decisions.

---

## Scripts

### `scripts/globe.py` — rotating globe animation (GIF + MP4)

Renders a full-rotation animation of the LCM-10 land cover layer draped on a
sphere using PyVista.  Outputs `globe_rotation_fps<N>.gif` and `.mp4`.

Dependencies: `pyvista rasterio imageio imageio-ffmpeg pillow`
