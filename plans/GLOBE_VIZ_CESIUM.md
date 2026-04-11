# Plan: Interactive Globe with CesiumJS

## Goal

A browser-based, interactive 3D globe with three layers stacked — mirroring `html/globe_maplibre.html` exactly in visual result and UI controls:

1. **Blue Marble** (background) — USGS imagery
2. **LCM-10 MAP** (foreground) — COG served via titiler
3. **Country borders** (top) — Natural Earth 50m GeoJSON, toggleable

The globe is freely rotatable and zoomable. The LCM-10 land cover layer sits on top of the Blue Marble imagery; ocean/no-data areas show the Blue Marble beneath. Country borders can be shown/hidden via a toggle button on the right side of the screen.

**Data sources:** see [`data.md`](data.md) for all URLs, specs, colormap, and access notes.

---

## Architecture

```
├── html/
│   ├── globe_maplibre.html   # existing MapLibre implementation
│   └── globe_cesium.html     # this implementation
└── plans/
    ├── GLOBE_VIZ_PLAN.md     # MapLibre architecture reference
    ├── GLOBE_VIZ_CESIUM.md   # this document
    └── data.md               # shared data sources spec
```

**Stack:**
- [CesiumJS](https://cesium.com/platform/cesiumjs/) — 3D globe engine (always-on globe, no projection setting needed)
- No build step — single HTML file, all dependencies via CDN
- [titiler.xyz](https://titiler.xyz/) public instance — serves XYZ tiles on-the-fly from the remote COG (same as MapLibre version)

### MapLibre → CesiumJS mapping

| Concern | MapLibre | CesiumJS |
|---|---|---|
| Globe renderer | `projection: { type: 'globe' }` | Always 3D — no config needed |
| Globe/flat toggle | `GlobeControl` | `sceneModePicker: true` (3D / 2D / Columbus) |
| WMS layer | `type:'raster'` + `{bbox-epsg-3857}` | `WebMapServiceImageryProvider` |
| XYZ raster tiles | `type:'raster'` + `{z}/{x}/{y}` | `UrlTemplateImageryProvider` + `{reverseY}` |
| Vector borders | `type:'geojson'` source + `type:'line'` layer | `GeoJsonDataSource.load()` with `fill: TRANSPARENT` |
| Borders visibility | `setLayoutProperty('visibility','none')` | `bordersDataSource.show = false` |
| Atmosphere off | `sky: { atmosphere-blend: 0 }`, no `light` | 7-property disable sequence (see Globe Setup) |
| Background black | `#map { background: #000 }` | `scene.backgroundColor = Cesium.Color.BLACK` |
| Attribution | `AttributionControl({ compact: true })` | `creditContainer` pointing to custom div |
| Load-event required | Yes — `map.on('load', ...)` | No — add layers immediately after construction |

---

## Globe Setup

### CDN (in `<head>`)

```html
<link rel="stylesheet" href="https://cesium.com/downloads/cesiumjs/releases/1.125/Build/Cesium/Widgets/widgets.css" />
<script src="https://cesium.com/downloads/cesiumjs/releases/1.125/Build/Cesium/Cesium.js"></script>
```

### Ion token

**We do not use any Cesium Ion-hosted assets** — all data (Blue Marble WMS, LCM-10 via titiler, country borders GeoJSON) is fetched directly from its own source. However, the CesiumJS library makes a background request to `ion.cesium.com` on startup and logs a warning when no token is set.

Two acceptable approaches:

**Option A — Free token (recommended, no console warnings):**
Register at `cesium.com/ion` (free tier, no credit card). Copy the auto-created "Default Token":
```js
Cesium.Ion.defaultAccessToken = 'YOUR_CESIUM_ION_TOKEN';
```

**Option B — Empty token (no signup, minor console warning only):**
```js
Cesium.Ion.defaultAccessToken = '';
```

CesiumJS renders correctly either way; no Ion assets are consumed in either case.

### Viewer constructor

```js
const viewer = new Cesium.Viewer('cesiumContainer', {
  animation:            false,
  timeline:             false,
  baseLayerPicker:      false,
  geocoder:             false,
  homeButton:           false,
  infoBox:              false,
  selectionIndicator:   false,
  navigationHelpButton: false,
  sceneModePicker:      true,   // 3D / 2D / Columbus toggle (replaces GlobeControl)
  baseLayer:            false,  // prevent default Bing Maps request
  creditContainer:      document.getElementById('cesium-credit'),
});
```

### Disabling atmosphere and lighting

CesiumJS has multiple independent atmosphere/lighting systems. All must be addressed to match the MapLibre uniform-look (`atmosphere-blend:0`, no directional `light`):

```js
viewer.scene.skyAtmosphere.show         = false; // blue halo at globe limb
viewer.scene.skyBox.show                = false; // star field background
viewer.scene.sun.show                   = false;
viewer.scene.moon.show                  = false;
viewer.scene.globe.showGroundAtmosphere = false; // darkens tiles at horizon edge
viewer.scene.globe.enableLighting       = false; // day/night terminator
viewer.scene.fog.enabled                = false;
viewer.scene.backgroundColor            = Cesium.Color.BLACK;
```

### Initial camera position

```js
// lon:10, lat:30, height ~15,000 km ≈ MapLibre center:[10,30] zoom:1.5
viewer.camera.setView({
  destination: Cesium.Cartesian3.fromDegrees(10, 30, 15000000),
  orientation: { heading: 0, pitch: -Cesium.Math.PI_OVER_TWO, roll: 0 },
});
```

---

## Layer Wiring

Data constants are identical to `globe_maplibre.html`:

```js
const COG_URL = encodeURIComponent(
  'https://vito-lcf-shapefiles-waw4-1.s3.waw4-1.cloudferro.com/LCM-10_v100_2020_MAP_lat-lon.tif'
);
const COLORMAP = encodeURIComponent(JSON.stringify({
  10:  [0,   100,   0, 255],  // Tree cover
  20:  [255, 187,  34, 255],  // Shrubland
  30:  [255, 255,  76, 255],  // Grassland
  40:  [240, 150, 255, 255],  // Cropland
  50:  [0,   150, 160, 255],  // Herbaceous wetland
  60:  [0,   207, 117, 255],  // Mangroves
  70:  [250, 230, 160, 255],  // Moss and lichen
  80:  [180, 180, 180, 255],  // Bare/sparse vegetation
  90:  [250,   0,   0, 255],  // Built-up
  100: [0,   100, 200, 255],  // Permanent water bodies
  110: [240, 240, 240, 255],  // Snow and ice
  254: [10,   10,  10, 255],  // Unclassifiable
  255: [0,     0,   0,   0],  // No-data → transparent
}));
```

Layers are added immediately after the Viewer is constructed (no `map.on('load')` equivalent needed):

```js
// Safety net: remove any default layer (belt-and-suspenders with baseLayer:false)
viewer.imageryLayers.removeAll();

// Layer 1 — Blue Marble (USGS WMS)
// Cesium's WebMapServiceImageryProvider handles BBOX natively in EPSG:4326.
// No {bbox-epsg-3857} template needed.
viewer.imageryLayers.addImageryProvider(new Cesium.WebMapServiceImageryProvider({
  url: 'https://basemap.nationalmap.gov/arcgis/services/USGSImageryOnly/MapServer/WMSServer',
  layers: '0',
  parameters: {
    SERVICE:     'WMS',
    VERSION:     '1.3.0',
    REQUEST:     'GetMap',
    FORMAT:      'image/png',
    TRANSPARENT: 'false',
    STYLES:      '',
  },
  credit: new Cesium.Credit('© USGS'),
}));

// Layer 2 — LCM-10 via titiler
// CRITICAL: use {reverseY}, not {y}.
// Cesium uses TMS-style (south-origin) Y; titiler expects XYZ/slippy (north-origin) Y.
// {reverseY} converts from TMS to XYZ before the HTTP request is made.
viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
  url: `https://titiler.xyz/cog/tiles/WebMercatorQuad/{z}/{x}/{reverseY}`
     + `?url=${COG_URL}&bidx=1&colormap=${COLORMAP}`,
  tileWidth: 256, tileHeight: 256,
  minimumLevel: 0, maximumLevel: 12,
  credit: new Cesium.Credit(
    "© VITO 2026. European Union's Copernicus Land Monitoring Service information. "
    + '<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank">CC-BY 4.0</a>',
    true,
  ),
}));

// Layer 3 — Country borders (GeoJsonDataSource, async)
// Polygon features are styled with no fill so the raster remains visible beneath.
const bordersDataSource = new Cesium.GeoJsonDataSource('country-borders');
bordersDataSource.load(
  'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson',
  {
    stroke:        Cesium.Color.BLACK.withAlpha(0.55), // matches MapLibre line-opacity:0.55
    fill:          Cesium.Color.TRANSPARENT,            // no fill — land-cover visible beneath
    strokeWidth:   1.0,                                 // WebGL caps lineWidth at 1px in most browsers
    clampToGround: true,                               // drape outlines on globe surface
  }
).then(function () {
  viewer.dataSources.add(bordersDataSource);
  // Wire toggle only after datasource is ready
  document.getElementById('borders-toggle').addEventListener('click', function () {
    bordersDataSource.show = !bordersDataSource.show;
    this.classList.toggle('active', bordersDataSource.show);
  });
});
```

---

## Legend

A fixed HTML/CSS panel (bottom-left) listing the 12 LCM-10 classes with coloured swatches. Identical structure to `globe_maplibre.html`. Colours from [`data.md §2 Colormap`](data.md#colormap).

### Eye-icon toggle

Same pattern as MapLibre version — a button with open/closed SVG eye icons, toggling a `.hidden` CSS class:

```css
#legend.hidden { opacity: 0; visibility: hidden; }
```

---

## Borders Toggle

Same button appearance (map/grid SVG, dark background, blue `.active` state) and position (right side, below top-right controls):

```js
// Wired inside bordersDataSource.load().then():
const btn = document.getElementById('borders-toggle');
btn.addEventListener('click', function () {
  bordersDataSource.show = !bordersDataSource.show;
  this.classList.toggle('active', bordersDataSource.show);
});
```

The `top:180px` offset places the button below the CesiumJS SceneModePicker and zoom buttons. Adjust after visual inspection if necessary.

---

## Attribution

Cesium's default credit container cannot be easily dark-themed via CSS class overrides. Redirect credits to a custom div:

```html
<div id="cesium-credit"></div>
```

```css
#cesium-credit { position: absolute; bottom: 5px; right: 10px;
                 font-size: 10px; color: #888;
                 background: rgba(0,0,0,0.6); padding: 2px 6px;
                 border-radius: 3px; z-index: 1; }
#cesium-credit a { color: #9bd; }
.cesium-credit-logoContainer { display: none !important; }
```

---

## Implementation Steps

1. Create `html/globe_cesium.html` based on `globe_maplibre.html` structure
2. Replace MapLibre CDN tags with CesiumJS CDN
3. Rename `<div id="map">` → `<div id="cesiumContainer">`, add `<div id="cesium-credit">`
4. Implement Viewer constructor with atmosphere/lighting disable sequence
5. Add layers (Blue Marble synchronous, LCM-10 synchronous, borders async)
6. Keep legend HTML/CSS/JS unchanged
7. Update borders toggle to use `bordersDataSource.show`
8. Style attribution container

### Verification checklist

- [ ] Black background, no atmosphere halo or stars
- [ ] Blue Marble satellite imagery covers globe
- [ ] LCM-10 tiles appear geographically correct (not vertically mirrored)
- [ ] LCM-10 transparent pixels reveal Blue Marble beneath
- [ ] Country borders visible as thin outlines (no fill)
- [ ] Borders toggle button shows/hides borders and changes colour
- [ ] Legend toggle (eye icon) shows/hides legend panel
- [ ] SceneModePicker switches 3D / 2D / Columbus
- [ ] Attribution dark-themed at bottom-right
- [ ] No console errors (CORS, 404 tiles, ion token)

---

## Key Dependencies

| Library | Version | CDN |
|---|---|---|
| CesiumJS JS | 1.125 | `https://cesium.com/downloads/cesiumjs/releases/1.125/Build/Cesium/Cesium.js` |
| CesiumJS CSS | 1.125 | `https://cesium.com/downloads/cesiumjs/releases/1.125/Build/Cesium/Widgets/widgets.css` |

CDN pattern for any version: `https://cesium.com/downloads/cesiumjs/releases/{VERSION}/Build/Cesium/Cesium.js`

---

## Research Findings: CesiumJS-Specific Notes

*From design review (2026-04-11).*

### `{reverseY}` is mandatory for titiler tiles

CesiumJS's `UrlTemplateImageryProvider` uses TMS-style tile Y (0 = south pole). titiler and MapLibre use XYZ/slippy Y (0 = north pole). Using `{y}` causes every tile to be the vertically mirrored row — land cover appears at the wrong latitude.

**Fix:** use `{reverseY}` — Cesium's built-in placeholder that converts TMS Y to XYZ Y before the HTTP request.

```
WRONG:   .../WebMercatorQuad/{z}/{x}/{y}?...
CORRECT: .../WebMercatorQuad/{z}/{x}/{reverseY}?...
```

### WMS uses EPSG:4326 automatically

`WebMapServiceImageryProvider` constructs tile bounding boxes internally in geographic space. Unlike MapLibre, no `{bbox-epsg-3857}` template or `addProtocol` workaround is needed. The USGS endpoint handles WMS 1.3.0 + EPSG:4326 correctly and Cesium manages axis ordering automatically.

### `maximumLevel: 12` prevents tile 404s

Without `maximumLevel`, Cesium requests tiles at whatever zoom the camera demands. The LCM-10 COG overviews typically cover only to zoom 12–14; requests beyond that return 404. Verify actual max zoom via:
```
https://titiler.xyz/cog/info?url=<encoded-url>
```

### No `map.on('load')` equivalent needed

Cesium is ready immediately after `new Cesium.Viewer()`. Imagery providers are added synchronously. Only `GeoJsonDataSource.load()` is async and requires a `.then()` callback.

### SceneModePicker vs MapLibre GlobeControl

| MapLibre GlobeControl | Cesium SceneModePicker |
|---|---|
| Toggles globe ↔ flat (Mercator) | Switches 3D globe / 2D Mercator / Columbus view |

Set `sceneModePicker: true` in the Viewer constructor. Switching modes resets camera position — users may need to re-navigate.

### Known limitations

| Limitation | Detail |
|---|---|
| WebGL `lineWidth` capped at 1px | Most browsers cap `lineWidth > 1` in WebGL; `strokeWidth` above 1 is silently clamped |
| GeoJSON entity-based (not tile-streamed) | All 3–4 MB of border GeoJSON is loaded and converted to entities at once |
| `maximumLevel` must be set | Omitting it causes 404s at high camera zoom |
| Ion token recommended | CesiumJS logs a warning without one, even when no ion assets are used |
| SceneMode transitions reset camera | Switching 3D/2D/Columbus resets the camera to a default view |
