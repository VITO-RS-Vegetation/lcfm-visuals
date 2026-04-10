# Plan: Interactive Rotatable Globe with MapLibre GL JS

## Goal

A browser-based, interactive rotatable globe with three layers stacked:

1. **Blue Marble** (background) — USGS imagery
2. **LCM-10 MAP** (foreground) — COG served via titiler
3. **Country borders** (top) — Natural Earth 50m GeoJSON line layer, toggleable

The globe is freely rotatable and zoomable. The LCM-10 land cover layer sits on top of the Blue Marble imagery; ocean/no-data areas show the Blue Marble beneath. Country borders can be shown/hidden via a toggle button on the right side of the screen.

**Data sources:** see [`data.md`](data.md) for all URLs, specs, colormap, and access notes.

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
- [MapLibre GL JS](https://maplibre.org/maplibre-gl-js/) ≥ 5.0 — map engine with globe projection
- [Vite](https://vitejs.dev/) + TypeScript — fast dev & build
- [titiler](https://titiler.xyz/) public instance — serves XYZ tiles on-the-fly from the remote COG

No swipe/compare control needed: both layers are on a single map instance.

---

## Globe Setup

```ts
const map = new maplibregl.Map({
  container: 'map',
  style: {
    version: 8,
    projection: { type: 'globe' },      // requires maplibre-gl v5+
    sky: { 'atmosphere-blend': 0 },     // disabled for uniform look; see findings below
    sources: {},
    layers: [],
    // NO 'light' property — directional sun darkens the opposite hemisphere
  },
  center: [10, 30],
  zoom: 1.5,
});

map.addControl(new maplibregl.NavigationControl());
map.addControl(new maplibregl.GlobeControl());         // user toggle globe ↔ flat
map.addControl(
  new maplibregl.AttributionControl({ compact: true }), // ⓘ icon; expands on click
  'bottom-right',
);
```

CSS for the space background:

```css
#map { background: #000; }
```

---

## Layer Wiring

Add sources and layers on `map.on('load', ...)`. Tile URLs and the colormap JSON are defined in [`data.md`](data.md).

```ts
map.on('load', () => {
  // Layer 1: Blue Marble (background)
  map.addSource('blue-marble', {
    type: 'raster',
    tiles: [
      'https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}',
    ],
    tileSize: 256,
    attribution: '© USGS',
  });
  map.addLayer({ id: 'blue-marble', type: 'raster', source: 'blue-marble' });

  // Layer 2: LCM-10 MAP (foreground)
  // COG_URL and COLORMAP constants — see data.md §2
  map.addSource('lcm10', {
    type: 'raster',
    tiles: [
      `https://titiler.xyz/cog/tiles/WebMercatorQuad/{z}/{x}/{y}`
      + `?url=${COG_URL}&bidx=1&colormap=${COLORMAP}`,
    ],
    tileSize: 256,
    attribution: '© VITO 2026. European Union\'s Copernicus Land Monitoring Service information. <a href="https://creativecommons.org/licenses/by/4.0/">CC-BY 4.0</a>',
  });
  map.addLayer({ id: 'lcm10', type: 'raster', source: 'lcm10',
    paint: { 'raster-opacity': 1.0 } });

  // Layer 3: Country borders (Natural Earth 50m) — see data.md §4
  map.addSource('country-borders', {
    type: 'geojson',
    data: 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson',
  });
  map.addLayer({
    id: 'country-borders',
    type: 'line',
    source: 'country-borders',
    layout: { 'line-join': 'round', 'line-cap': 'round', 'visibility': 'visible' },
    paint: { 'line-color': '#000000', 'line-width': 0.7, 'line-opacity': 0.55 },
  });
});

// Toggle button (right side, below MapLibre controls):
const bordersBtn = document.getElementById('borders-toggle');
bordersBtn.addEventListener('click', function () {
  const next = map.getLayoutProperty('country-borders', 'visibility') === 'visible' ? 'none' : 'visible';
  map.setLayoutProperty('country-borders', 'visibility', next);
  bordersBtn.classList.toggle('active', next === 'visible');
});
```

---

## Legend

A fixed HTML/CSS panel (bottom-left) listing the 12 LCM-10 classes with coloured swatches. Colours are defined in [`data.md §2 Colormap`](data.md#colormap).

### Eye-icon toggle

A small button with an SVG eye / eye-off icon controls legend visibility. Toggling adds/removes a `.hidden` class:

```css
#legend.hidden { opacity: 0; visibility: hidden; }
```

The toggle swaps between two inline SVG icons (`#eye-open` / `#eye-shut`) on each click.

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
   - `attributionControl: false` on the Map constructor (added manually as compact)

3. **`src/main.ts`**
   - Initialise map with globe projection and blank style (no `light`, `atmosphere-blend: 0`)
   - On `load`: add Blue Marble source/layer, then LCM-10 source/layer
   - Add `NavigationControl`, `GlobeControl`, compact `AttributionControl`

4. **Verify titiler COG access**
   ```
   https://titiler.xyz/cog/info?url=<encoded-s3-url>
   ```
   Confirm bands, CRS, and overviews are reported correctly.

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

CDN alternative (as used in `globe_maplibre.html`):
```html
<link rel='stylesheet' href='https://unpkg.com/maplibre-gl@5.22.0/dist/maplibre-gl.css' />
<script src='https://unpkg.com/maplibre-gl@5.22.0/dist/maplibre-gl.js'></script>
```

---

## Research Findings: MapLibre Globe

*Based on review of official MapLibre docs, roadmap, and style spec (2026-04-09).*

### Globe requires MapLibre GL JS v5.0.0+

Globe projection was released in January 2025 with v5.0.0; it is not available in v4.x.

```bash
npm install maplibre-gl@^5
```

### Adaptive Composite Map Projection

MapLibre's globe uses an **Adaptive Composite Map Projection**:
- At low zoom (zoomed out): renders as a sphere
- Around **zoom ~12**: automatically transitions to Mercator — float32 GPU precision (~1 float per 2.5 m) is insufficient for high-zoom globe rendering
- Raster tiles are client-side reprojected from WebMercator; no server-side changes needed

### Two ways to enable globe

**Option A — in the style object (preferred for initial load as globe):**

```ts
style: {
  version: 8,
  projection: { type: 'globe' },
  sources: {},
  layers: [],
}
```

**Option B — programmatically after style loads:**

```ts
map.on('style.load', () => {
  map.setProjection({ type: 'globe' });
});
```

> Calling `setProjection()` *before* `style.load` throws an error. Use `style.load`, not `load`.

### GlobeControl

MapLibre v5 ships a built-in `GlobeControl` that lets users toggle globe/flat:

```ts
map.addControl(new maplibregl.GlobeControl());
```

### Sky / atmosphere layer

| Property | Default | Description |
|---|---|---|
| `atmosphere-blend` | `0.8` | 1 = atmosphere fully visible, 0 = hidden |
| `sky-color` | `#88C6FC` | Base sky colour |
| `horizon-color` | `#ffffff` | Horizon colour |

Zoom-interpolated setup:
```ts
sky: {
  'atmosphere-blend': [
    'interpolate', ['linear'], ['zoom'],
    0, 1,   // fully visible at zoom 0–5
    5, 1,
    7, 0,   // faded by zoom 7
  ],
},
```

### Projection style spec

Available named types: `"mercator"`, `"globe"`, `"vertical-perspective"`.
The `type` property supports interpolate expressions for dynamic transitions:

```ts
projection: {
  type: ['interpolate', ['linear'], ['zoom'], 10, 'vertical-perspective', 12, 'mercator']
}
```

### Official examples

| Example | URL |
|---|---|
| Globe with atmosphere | `/display-a-globe-with-an-atmosphere/` |
| Globe with vector map | `/display-a-globe-with-a-vector-map/` |
| Globe with fill extrusion | `/display-a-globe-with-a-fill-extrusion-layer/` |
| Custom layer with tiles on globe | `/add-a-custom-layer-with-tiles-to-a-globe/` |

All at <https://maplibre.org/maplibre-gl-js/docs/examples/>. The **"Display a globe with an atmosphere"** example is the closest reference (raster satellite tiles + globe + atmosphere).

### Known limitations

| Limitation | Detail |
|---|---|
| Auto-transition at zoom ~12 | Globe → Mercator due to float32 GPU precision |
| No polar camera movement | Camera movement across the poles is unsupported |
| `setMaxBounds` broken | Does not work in globe projection |
| `setLocationAtPoint` unreliable | May fail at certain parameter combinations |
| MapLibre Native | Globe is **not** available in MapLibre Native (mobile/desktop) |
| `flyTo`/`easeTo` zoom drift | Simultaneous lat+zoom change can cause planet-size fluctuation |

---

## Implementation Findings (from globe_maplibre.html)

*From live testing (2026-04-09).*

### Uniform globe lighting

Two separate properties cause uneven illumination:

1. **`light: { anchor: 'map', position: [...] }`** — positions a directional sun, darkening the opposite hemisphere. **Fix: omit the `light` property entirely.**
2. **`sky: { 'atmosphere-blend': > 0 }`** — even without directional light, a value > 0 renders a bright atmospheric halo visible as a sliver at the globe limb. **Fix: set `atmosphere-blend: 0`.**

### htmlpreview.github.io: use `setInterval` poll, not `onload`

htmlpreview patches `document.head.appendChild` so that `script.onload` is called **synchronously** before the script content has executed. A dynamic `<script>` loader using `js.onload = initMap` therefore calls `initMap()` before `maplibregl` is defined.

**Fix:** poll with `setInterval` until `window.maplibregl` is truthy:

```js
(function () {
  var js = document.createElement('script');
  js.src = 'https://unpkg.com/maplibre-gl@5.22.0/dist/maplibre-gl.js';
  document.head.appendChild(js);
  var t = setInterval(function () {
    if (window.maplibregl) { clearInterval(t); initMap(); }
  }, 50);
})();
```

**GitHack** (`raw.githack.com`) serves HTML files as-is without script interception and is more reliable than htmlpreview. GitHack caches branch-based URLs — always use a **commit-SHA URL** after a new push:

```
https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/<sha>/html/globe_maplibre.html
```

Get the SHA with `git rev-parse HEAD`.

### Attribution control: compact by default

```ts
const map = new maplibregl.Map({
  attributionControl: false,   // disable auto-added control
  // ...
});
map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
```

Dark-theme CSS overrides:

```css
.maplibregl-ctrl-attrib          { background: rgba(0,0,0,0.6) !important; color: #ccc !important; }
.maplibregl-ctrl-attrib a        { color: #9bd !important; }
.maplibregl-ctrl-attrib-button   { filter: invert(0.8); }
```
