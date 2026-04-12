# Claude Code Instructions

## Globe Visualizations (Cesium, MapLibre)

Whenever you create or modify an HTML globe visualization file (e.g. any `*.html` file using Cesium or MapLibre GL JS), **always generate a GitHack preview link** after committing.

### How to generate the preview link

1. After committing, get the full commit SHA:
   ```bash
   git rev-parse HEAD
   ```

2. Construct the preview URL using the SHA (not a branch name) to avoid CDN caching:
   ```
   https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/<full-sha>/html/<filename>.html
   ```

3. Output the link to the user so they can open it directly in a browser.

### Example

```
Preview: https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/32ba1b1f8c.../html/globe_maplibre.html
```

### Why GitHack with a SHA?

- GitHack serves raw GitHub files with correct MIME types (unlike `raw.githubusercontent.com`), making HTML files render properly in the browser.
- Using the commit SHA instead of a branch name (`main`) bypasses GitHack's CDN cache, ensuring the preview always reflects the exact committed state.

---

## Plans folder (`plans/`)

Reference documents, design decisions, and data specifications for this project.

| File | Summary |
|---|---|
| [`data.md`](plans/data.md) | Data sources reference: COG specs, asset URLs, colormap, and titiler tiling config for LCM-10, Blue Marble WMS, and Natural Earth country borders. |
| [`GLOBE_VIZ_PLAN.md`](plans/GLOBE_VIZ_PLAN.md) | Implementation plan for the interactive rotatable globe built with MapLibre GL JS (`html/globe_maplibre.html`). |
| [`GLOBE_VIZ_CESIUM.md`](plans/GLOBE_VIZ_CESIUM.md) | Implementation plan for an equivalent interactive 3D globe built with CesiumJS, mirroring the MapLibre version in features and UI. |
| [`lcm10_enhancements.md`](plans/lcm10_enhancements.md) | Planned enhancements to the LCM-10 visualisation layer (higher-resolution tiles, etc.). |
