# Plan: Interactive Rotatable Globe with MapLibre GL JS

## Goal

A browser-based, interactive rotatable globe with two raster layers stacked:

1. **Blue Marble** (background) — USGS imagery WMS
2. **LCM-10 MAP** (foreground, semi-transparent) — COG served via titiler

The globe is freely rotatable and zoomable. The LCM-10 land cover layer sits on top of the Blue Marble imagery, using its alpha band for transparency so ocean/no-data areas show the Blue Marble beneath.

Reference example: [anymap-ts control_grid](https://ts.anymap.dev/examples/maplibre/control_grid.html)  
Source: [control-grid-main.ts](https://github.com/opengeos/anymap-ts/blob/main/examples/maplibre/control-grid-main.ts)

---

## Architecture

```
├── index.html           # entry point
├── src/
│   └── main.ts          # map init, layer setup, legend
├── package.json
└── vite.config.ts
```

**Stack:**
- [MapLibre GL JS](https://maplibre.org/maplibre-gl-js/) ≥ 4.0 — map engine with globe projection
- [Vite](https://vitejs.dev/) + TypeScript — fast dev & build
- [titiler](https://titiler.xyz/) public instance — serves XYZ tiles on-the-fly from the remote COG

No swipe/compare control needed: both layers are on a single map instance.

---

## Layer 1 (background): Blue Marble (USGS WMS)

**Source:** `https://basemap.nationalmap.gov/arcgis/services/USGSImageryOnly/MapServer/WMSServer`

```ts
map.addSource('blue-marble', {
  type: 'raster',
  tiles: [
    'https://basemap.nationalmap.gov/arcgis/services/USGSImageryOnly/MapServer/WMSServer'
    + '?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0'
    + '&LAYERS=0&STYLES=&FORMAT=image/png&TRANSPARENT=false'
    + '&CRS=EPSG:4326&WIDTH=256&HEIGHT=256&BBOX={bbox-epsg-4326}',
  ],
  tileSize: 256,
  attribution: '© USGS',
});
map.addLayer({ id: 'blue-marble', type: 'raster', source: 'blue-marble' });
```

> Using EPSG:4326 (equirectangular) avoids the strong polar distortion/artefacts that occur with
> EPSG:3857 (WebMercator). The WMS is queried with WMS 1.3.0 (`CRS=`) and `{bbox-epsg-4326}`
> (axis order: minLat,minLon,maxLat,maxLon). Confirmed working — see `plans/data_findings.md`.

---

## Layer 2 (foreground): LCM-10 MAP (COG via titiler)

**Asset:** `https://vito-lcf-shapefiles-waw4-1.s3.waw4-1.cloudferro.com/LCM-10_v100_2020_MAP_lat-lon.tif` *(S3/CloudFerro — public HTTPS, HTTP range requests supported)*  
**Asset (Terrascope):** `https://services.terrascope.be/download/LCFM/products/LCM-10/v100/overviews/LCM-10_v100_2020_MAP_lat-lon.tif` *(online — requires authentication, HTTP 401)*  
**CRS:** EPSG:4326 | **Size:** 36000 × 14275 px  
**Coverage:** 180°W–180°E, 60°S–83°N  
**Bands:** Band 1 = MAP (uint8, categorical), Band 2 = alpha  
**No-data value:** 255 (transparent; distinct from class 254 = Unclassifiable)  
**License:** [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)  
**Attribution:** © VITO (Copernicus Land Monitoring Service / ESA, 2020). Made with Sentinel-1, Sentinel-2, AgERA5, and WorldDEM-30.

### COG Architecture

The global mosaic COG is built from **2,647 individual 3×3 degree tiles** distributed via the Terrascope STAC collection [`lcfm-lcm-10`](https://stac.terrascope.be/collections/lcfm-lcm-10). Each tile is a single-band uint8 Cloud-Optimized GeoTIFF (~5–32 MB) following the naming convention:

```
LCFM_LCM-10_V100_2020_{LAT}{LON}_MAP.tif
```

Example tile URL (authentication required):
```
https://services.terrascope.be/download/LCFM/products/LCM-10/v100/tiles_latlon/3deg/S60/W030/2020/LCFM_LCM-10_V100_2020_S60W030_MAP.tif
```

The native `titiler.terrascope.be` endpoint supports a named `lcfm` colormap for tile previews but requires OIDC authentication. The public `titiler.xyz` instance with the explicit colormap below is used instead for the overview COG.

### Tiling via titiler

[titiler.xyz](https://titiler.xyz/) is a free public COG tile server. The browser requests
standard XYZ tiles from titiler.xyz; titiler fetches the COG from the S3 bucket server-side.
No CORS issues in the browser — the browser only talks to titiler.xyz.

```ts
const COG_URL = encodeURIComponent(
  'https://vito-lcf-shapefiles-waw4-1.s3.waw4-1.cloudferro.com/LCM-10_v100_2020_MAP_lat-lon.tif'
);
// Terrascope URL is online but requires authentication (HTTP 401).
// 'https://services.terrascope.be/download/LCFM/products/LCM-10/v100/overviews/LCM-10_v100_2020_MAP_lat-lon.tif'
const COLORMAP = encodeURIComponent(JSON.stringify({
  10:  [0,   100, 0,   255],   // Tree cover         #006400
  20:  [255, 187, 34,  255],   // Shrubland          #FFBB22
  30:  [255, 255, 76,  255],   // Grassland          #FFFF4C
  40:  [240, 150, 255, 255],   // Cropland           #F096FF
  50:  [0,   150, 160, 255],   // Herbaceous wetland #0096A0
  60:  [0,   207, 117, 255],   // Mangroves          #00CF75
  70:  [250, 230, 160, 255],   // Moss and lichen    #FAE6A0
  80:  [180, 180, 180, 255],   // Bare/sparse veg    #B4B4B4
  90:  [250, 0,   0,   255],   // Built-up           #FA0000
  100: [0,   100, 200, 255],   // Permanent water    #0064C8
  110: [240, 240, 240, 255],   // Snow and ice       #F0F0F0
  254: [10,  10,  10,  255],   // Unclassifiable     #0A0A0A
  // 255 = No-data; handled by the alpha band (band 2), not the colormap.
}));

map.addSource('lcm10', {
  type: 'raster',
  tiles: [
    `https://titiler.xyz/cog/tiles/WebMercatorQuad/{z}/{x}/{y}@2x`
    + `?url=${COG_URL}`
    + `&bidx=1&bidx=2`       // band 1 = data, band 2 = alpha
    + `&colormap=${COLORMAP}`,
  ],
  tileSize: 512,
  attribution: '© VITO 2026 / Copernicus',
});
map.addLayer({
  id: 'lcm10',
  type: 'raster',
  source: 'lcm10',
  paint: { 'raster-opacity': 1.0 },
});
```

> **Alpha band:** Requesting `bidx=1&bidx=2` tells titiler to treat band 2 as an alpha mask.
> Ocean/no-data pixels are fully transparent, revealing the Blue Marble background.

> **Fallback:** If the public titiler instance is insufficient (rate limits), self-host via Docker:
> ```bash
> docker run -p 8000:8000 ghcr.io/developmentseed/titiler:latest
> ```
> Then replace `https://titiler.xyz` with `http://localhost:8000`.

---

## Globe Setup

```ts
const map = new maplibregl.Map({
  container: 'map',
  style: {
    version: 8,
    sources: {},
    layers: [],
    sky: {},
  },
  center: [10, 30],
  zoom: 1.5,
  projection: { type: 'globe' },   // MapLibre ≥ 4.0
});

map.addControl(new maplibregl.NavigationControl());

map.on('load', () => {
  // add blue-marble source + layer
  // add lcm10 source + layer
});
```

> Globe projection (`type: 'globe'`) requires MapLibre GL JS ≥ 4.0.

---

## Legend

A fixed HTML/CSS panel (bottom-left) listing the 12 LCM-10 classes with coloured swatches:

| Value | Class | Colour |
|---|---|---|
| 10 | Tree cover | `#006400` |
| 20 | Shrubland | `#FFBB22` |
| 30 | Grassland | `#FFFF4C` |
| 40 | Cropland | `#F096FF` |
| 50 | Herbaceous wetland | `#0096A0` |
| 60 | Mangroves | `#00CF75` |
| 70 | Moss and lichen | `#FAE6A0` |
| 80 | Bare/sparse vegetation | `#B4B4B4` |
| 90 | Built-up | `#FA0000` |
| 100 | Permanent water bodies | `#0064C8` |
| 110 | Snow and ice | `#F0F0F0` |
| 254 | Unclassifiable | `#0A0A0A` |
| 255 | No-data | transparent (alpha band) |

---

## Implementation Steps

1. **Scaffold project**
   ```bash
   npm create vite@latest lcfm-globe -- --template vanilla-ts
   cd lcfm-globe
   npm install maplibre-gl
   ```

2. **`index.html`**
   - Single `<div id="map">` full-screen
   - Import MapLibre CSS
   - Legend div with class swatches (static HTML)

3. **`src/main.ts`**
   - Initialise map with globe projection and blank style
   - On `load`: add Blue Marble source/layer, then LCM-10 source/layer
   - Add `NavigationControl`

4. **Verify titiler COG access**
   - Hit `https://titiler.xyz/cog/info?url=<encoded-url>` in a browser
   - Confirm bands, CRS, overviews are reported correctly

5. **Build & deploy**
   ```bash
   npm run build   # outputs dist/
   ```
   Deploy `dist/` as a static site (GitHub Pages, Netlify, etc.)

---

## Key Dependencies

| Package | Version | Purpose |
|---|---|---|
| `maplibre-gl` | `^5.0` | Map engine + globe projection (globe requires v5+) |
| `vite` | `^5` | Build tool |

---

## Open Questions / Risks

| Item | Notes |
|---|---|
| titiler rate limits | Public instance may throttle at scale. Self-host via Docker if needed. |
| S3 COG accessibility | `vito-lcf-shapefiles-waw4-1.s3.waw4-1.cloudferro.com` responds HTTP 200 with `accept-ranges: bytes` — range requests confirmed working. |
| Terrascope COG (auth) | Endpoint is online (HTTP 401 = requires credentials). Terrascope uses OIDC; obtain login to use it as an alternative. Individual tiles also require auth. |
| titiler `bidx=1&bidx=2` + colormap | Need to confirm titiler applies colormap to band 1 and uses band 2 as alpha in the same request. May need `&return_mask=true` instead. |
| No-data value 255 | Per STAC metadata, 255 = no-data. Alpha band (band 2) should already mask these pixels; verify no bleed-through of value 255 as near-white. |
| Globe projection in MapLibre | **Resolved:** Globe is a v5.0.0 feature (released January 2025), not v4.x. Update dependency to `maplibre-gl@^5`. See research below. |
| Tile count / coverage | 2,647 tiles cover 60°S–83°N. Polar regions beyond 83°N (Greenland ice cap fringe, High Arctic) and below 60°S (Antarctica) are not included in the dataset. |

---

## Research Findings: MapLibre Globe Examples & Docs

*Appended 2026-04-09 based on review of official MapLibre docs, roadmap, and style spec.*

### Version Correction

**Globe projection requires MapLibre GL JS v5.0.0+** (released January 2025). It was *not* available in v4.x. The plan's original dependency `^4.0` must be updated to `^5.0`.

```bash
npm install maplibre-gl@^5
```

CDN (as used in official examples):
```html
<link rel='stylesheet' href='https://unpkg.com/maplibre-gl@5.22.0/dist/maplibre-gl.css' />
<script src='https://unpkg.com/maplibre-gl@5.22.0/dist/maplibre-gl.js'></script>
```

---

### How Globe Projection Works (Adaptive Composite Map Projection)

MapLibre's globe uses an **Adaptive Composite Map Projection**:
- At low zoom (zoomed out): renders as a sphere (globe)
- Around **zoom ~12**: automatically transitions back to Mercator — float32 precision in shaders (~1 float per 2.5 m) is insufficient for high-zoom globe rendering
- Raster tiles are client-side reprojected from WebMercator; no server-side changes needed

The planet also automatically enlarges when the map center approaches the poles to maintain visual consistency.

---

### Two Ways to Enable Globe

**Option A — in the style object (preferred for initial load as globe):**

```ts
const map = new maplibregl.Map({
  container: 'map',
  style: {
    version: 8,
    projection: { type: 'globe' },   // ← here in style spec
    sources: {},
    layers: [],
    sky: {},
  },
  center: [10, 30],
  zoom: 1.5,
});
```

**Option B — programmatically after style loads:**

```ts
map.on('style.load', () => {
  map.setProjection({ type: 'globe' });
});
```

> **Important:** Calling `setProjection()` *before* `style.load` throws an error. Use `style.load`, not `load`.

---

### GlobeControl (UI Toggle)

MapLibre v5 ships a built-in `GlobeControl` that lets users toggle globe/flat:

```ts
map.addControl(new maplibregl.GlobeControl());
```

This is optional — omit for a fixed-globe experience. The control auto-updates when `map.setProjection()` is called programmatically.

---

### Sky / Atmosphere Layer

The `sky` style layer adds an atmospheric halo around the globe edge. The key property is `atmosphere-blend`:

| Property | Type | Default | Description |
|---|---|---|---|
| `atmosphere-blend` | number [0–1] | `0.8` | 1 = atmosphere fully visible, 0 = hidden. Recommended to interpolate with zoom. |
| `sky-color` | color | `#88C6FC` | Base sky colour |
| `horizon-color` | color | `#ffffff` | Horizon colour |
| `sky-horizon-blend` | number [0–1] | `0.8` | Blend between sky and horizon colours |

**Recommended zoom-interpolated atmosphere setup:**

```ts
// In the style spec (sky property):
sky: {
  'atmosphere-blend': [
    'interpolate', ['linear'], ['zoom'],
    0, 1,   // fully visible at zoom 0
    5, 1,   // still fully visible at zoom 5
    7, 0,   // faded out by zoom 7
  ],
},
```

Or programmatically: `map.setSky({ 'atmosphere-blend': 1.0 })`.

**Recommended CSS for the space background effect:**

```css
#map { background: #000; }   /* black "space" shows around globe edge */
```

---

### Light Configuration (Sun Position)

The globe atmosphere looks most realistic with a directional light simulating the sun:

```ts
// In style spec:
light: {
  anchor: 'map',
  position: [1.5, 90, 80],   // [radial distance, azimuth°, polar angle°]
},
```

This is set at the style level. Can also be updated via `map.setLight(...)`.

---

### Official Globe Examples (MapLibre Docs)

All available at <https://maplibre.org/maplibre-gl-js/docs/examples/>:

| Example | URL | Notes |
|---|---|---|
| Globe with atmosphere | `/display-a-globe-with-an-atmosphere/` | Satellite raster + sky layer + light; best reference for this project |
| Globe with vector map | `/display-a-globe-with-a-vector-map/` | Minimal `setProjection` pattern |
| Globe with fill extrusion | `/display-a-globe-with-a-fill-extrusion-layer/` | 3D buildings on globe |
| Custom layer with tiles on globe | `/add-a-custom-layer-with-tiles-to-a-globe/` | WebGL custom tile rendering |
| Simple custom layer on globe | `/add-a-simple-custom-layer-on-a-globe/` | Basic WebGL on globe |
| Heatmap on globe with terrain | `/create-a-heatmap-layer-on-a-globe-with-terrain-elevation/` | Terrain + heatmap |
| Zoom/planet size relation | (zoom-planet-size example) | `flyTo`/`easeTo` zoom compensation |
| 3D model on globe (three.js) | `/add-a-3d-model-to-globe-using-three-js/` | three.js integration |

The **"Display a globe with an atmosphere"** example is the closest reference to this project (raster satellite tiles + globe + atmosphere).

**Key details from that example:**
- Satellite source: EOX S2Cloudless 2020: `https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{y}/{x}.jpg`
- Projection set in style spec directly (`'projection': {'type': 'globe'}`)
- Zoom 0, center on Japan coast
- Sky `atmosphere-blend` interpolated 0→5→7 zoom

---

### Projection Style Spec Reference

From <https://maplibre.org/maplibre-style-spec/projection/>:

- Default projection: `"mercator"`
- Globe is set as `{ "type": "globe" }`
- The `type` property **supports interpolate expressions**, enabling dynamic transitions:

```ts
// Transition globe → mercator between zoom 10–12:
projection: {
  type: ['interpolate', ['linear'], ['zoom'], 10, 'vertical-perspective', 12, 'mercator']
}
```

Available named types: `"mercator"`, `"globe"`, `"vertical-perspective"`. (The `"globe"` preset is a preconfigured composite of vertical-perspective + mercator with built-in breakpoints.)

---

### Known Limitations & Unsupported Features

| Limitation | Detail |
|---|---|
| Auto-transition at zoom ~12 | Globe → Mercator due to float32 GPU precision limits |
| No polar camera movement | Camera movement across the poles is unsupported |
| `setMaxBounds` broken | `maxBounds` / `setMaxBounds` does not work in globe projection (open issue) |
| `setLocationAtPoint` unreliable | May fail at certain parameter combinations |
| MapLibre Native | Globe is **not** available in MapLibre Native (mobile/desktop); only GL JS (web) |
| GPU `atan` inaccuracy | MapLibre draws 1×1 px framebuffers every second to measure and compensate for vendor-specific GPU `atan` errors |
| `flyTo`/`easeTo` zoom drift | Simultaneous lat+zoom change can cause planet-size fluctuation; must manually compensate zoom |

---

### Additional Reference: Stadia Maps Globe Tutorial

<https://docs.stadiamaps.com/tutorials/3d-globe-view-with-maplibre-gl-js/>

Key additional tips from this tutorial:
- Upgrade to MapLibre v5+ is required
- `GlobeControl` for user-facing toggle: `map.addControl(new maplibregl.GlobeControl())`
- Dark CSS background (`hsl(0, 0%, 2%)`) enhances readability
- RTL text plugin recommended for full language support: `maplibregl.setRTLTextPlugin(...)`

---

### Revised Globe Setup (incorporating all findings)

```ts
const map = new maplibregl.Map({
  container: 'map',
  style: {
    version: 8,
    projection: { type: 'globe' },      // requires maplibre-gl v5+
    sources: {},
    layers: [],
    sky: {
      'atmosphere-blend': [
        'interpolate', ['linear'], ['zoom'],
        0, 1,   // fully visible at zoom 0–5
        5, 1,
        7, 0,   // faded by zoom 7
      ],
    },
    light: {
      anchor: 'map',
      position: [1.5, 90, 80],
    },
  },
  center: [10, 30],
  zoom: 1.5,
});

map.addControl(new maplibregl.NavigationControl());
// Optional: user toggle between globe and flat
// map.addControl(new maplibregl.GlobeControl());

map.on('load', () => {
  // add blue-marble source + layer
  // add lcm10 source + layer
});
```

> `projection` set in the style spec at construction time — no need to call `setProjection()` on `style.load` if the style object is provided inline.
