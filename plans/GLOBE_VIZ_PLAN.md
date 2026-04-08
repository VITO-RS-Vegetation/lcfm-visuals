# Plan: Interactive Rotatable Globe with MapLibre GL JS

## Goal

A browser-based, interactive rotatable globe with two raster layers stacked:

1. **Blue Marble** (background) — USGS imagery WMS
2. **LCM-10 MAP** (foreground, semi-transparent) — COG served via titiler

The globe is freely rotatable and zoomable. The LCM-10 land cover layer sits on top of the Blue Marble imagery, using its alpha band for transparency so ocean/no-data areas show the Blue Marble beneath.

Reference example: [anymap-ts control_grid](https://ts.anymap.dev/examples/maplibre/control_grid.html)  
Source: [control-grid-main.ts](https://github.com/opengeos/anymap-ts/blob/main/examples/maplibre/control-grid-main.ts)

---

## LCM-10 Dataset

**STAC collection:** `https://stac.terrascope.be/collections/lcfm-lcm-10`  
**Title:** Annual Land Cover Map at 10 m resolution (LCFM)  
**License:** CC-BY-4.0  
**DOI:** `10.2909/602507b2-96c7-47bb-b79d-7ba25e97d0a9`  
**Citation:** Land Cover 2020 (raster 10 m), global, annual - version 1. European Union's Copernicus Land Monitoring Service information. DOI: https://doi.org/10.2909/602507b2-96c7-47bb-b79d-7ba25e97d0a9

**Attribution (full):**
> European Union's Copernicus Land Monitoring Service information; generated using Copernicus Climate Change Service information (AgERA5); contains modified Copernicus Sentinel data (2020); produced using Copernicus WorldDEM-30 © DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH 2014–2018 provided under COPERNICUS by the European Union and ESA.

**Providers:**
- European Commission — licensor
- Copernicus Land Monitoring Service (CLMS) — licensor
- European Space Agency (ESA) — producer
- VITO — processor & host

### Tile Architecture

The collection is stored as **3×3 degree WGS84 tiles** (e.g. `S60W030`, `S57W075`). Each tile is:
- **Size:** 36,000 × 36,000 px
- **Resolution:** 10 m GSD
- **Format:** Cloud-Optimized GeoTIFF (COG), uint8
- **Nodata:** 255
- **Band:** single band `MAP` (categorical, uint8)
- **Auth:** OIDC via Terrascope SSO (`https://sso.terrascope.be/auth/realms/terrascope/`)

Individual tiles require authentication and are not suitable for direct browser access.

### Overview COG (used for this visualization)

A pre-built overview COG is derived from all 3×3 degree tiles and is hosted on a public S3 bucket without authentication:

| Asset key | URL | Bands | Shape | Auth |
|---|---|---|---|---|
| `overview_lat_lon` | `https://services.terrascope.be/download/LCFM/products/LCM-10/v100/overviews/LCM-10_v100_2020_MAP_lat-lon.tif` | MAP + alpha | 14275 × 36000 | required (HTTP 401) |
| *(public S3 mirror)* | `https://vito-lcf-shapefiles-waw4-1.s3.waw4-1.cloudferro.com/LCM-10_v100_2020_MAP_lat-lon.tif` | MAP + alpha | 14275 × 36000 | none — range requests confirmed working |
| `overview_lat_lon_bg` | `https://services.terrascope.be/download/LCFM/products/LCM-10/v100/overviews/LCM-10_v100_2020_MAP_lat-lon_bg.tif` | RGBA (Blue Marble composite) | 2160 × 4320 | required |

**Overview COG band layout:**
- Band 1: `MAP` — categorical land cover value (uint8; nodata = 255)
- Band 2: `alpha` — transparency mask (255 = opaque land, 0 = ocean/no-data)

**Spatial coverage:** -180° to 180° lon, -60° to 83° lat (EPSG:4326)

**Render hints (from STAC `renders`):**
- `colormap_name`: `lcfm` (matches the class palette below)
- `resampling`: `mode` (correct for categorical data — most common value per pixel)
- Zoom range (EPSG:3857): **6 – 14**

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

**Asset:** `https://vito-lcf-shapefiles-waw4-1.s3.waw4-1.cloudferro.com/LCM-10_v100_2020_MAP_lat-lon.tif`
*(public S3/CloudFerro — no auth required, HTTP range requests confirmed working)*

**CRS:** EPSG:4326 | **Shape:** 36000 × 14275 px | **Coverage:** -180° to 180°, -60° to 83°  
**Bands:** Band 1 = MAP (categorical uint8, nodata=255), Band 2 = alpha  
**Nodata value:** 255 (unclassified/outside coverage — masked by the alpha band)

### Tiling via titiler

[titiler.xyz](https://titiler.xyz/) is a free public COG tile server. The browser requests
standard XYZ tiles from titiler.xyz; titiler fetches the COG from the S3 bucket server-side.
No CORS issues in the browser — the browser only talks to titiler.xyz.

```ts
const COG_URL = encodeURIComponent(
  'https://vito-lcf-shapefiles-waw4-1.s3.waw4-1.cloudferro.com/LCM-10_v100_2020_MAP_lat-lon.tif'
);
// Terrascope overview URL requires authentication (HTTP 401).
// 'https://services.terrascope.be/download/LCFM/products/LCM-10/v100/overviews/LCM-10_v100_2020_MAP_lat-lon.tif'

const COLORMAP = encodeURIComponent(JSON.stringify({
  10:  [0,   100, 0,   255],   // Tree cover              #006400
  20:  [255, 187, 34,  255],   // Shrubland               #FFBB22
  30:  [255, 255, 76,  255],   // Grassland               #FFFF4C
  40:  [240, 150, 255, 255],   // Cropland                #F096FF
  50:  [0,   150, 160, 255],   // Herbaceous wetland      #0096A0
  60:  [0,   207, 117, 255],   // Mangroves               #00CF75
  70:  [250, 230, 160, 255],   // Moss and lichen         #FAE6A0
  80:  [180, 180, 180, 255],   // Bare/sparse vegetation  #B4B4B4
  90:  [250, 0,   0,   255],   // Built-up                #FA0000
  100: [0,   100, 200, 255],   // Permanent water bodies  #0064C8
  110: [240, 240, 240, 255],   // Snow and ice            #F0F0F0
  254: [10,  10,  10,  255],   // Unclassifiable          #0A0A0A
}));

map.addSource('lcm10', {
  type: 'raster',
  tiles: [
    `https://titiler.xyz/cog/tiles/WebMercatorQuad/{z}/{x}/{y}@2x`
    + `?url=${COG_URL}`
    + `&bidx=1&bidx=2`            // band 1 = MAP, band 2 = alpha
    + `&colormap=${COLORMAP}`
    + `&resampling=mode`,         // mode resampling — correct for categorical data
  ],
  tileSize: 512,
  attribution: '© European Union\'s Copernicus Land Monitoring Service / VITO',
  minzoom: 0,
  maxzoom: 14,                    // STAC render hint: zoom 6–14 for EPSG:3857
});
map.addLayer({
  id: 'lcm10',
  type: 'raster',
  source: 'lcm10',
  paint: { 'raster-opacity': 1.0 },
});
```

> **Alpha band:** Requesting `bidx=1&bidx=2` tells titiler to treat band 2 as an alpha mask.
> Ocean/no-data pixels are fully transparent (alpha=0), revealing the Blue Marble background.
> Nodata value 255 in band 1 is already excluded by the alpha mask.

> **Resampling:** `mode` is specified in the STAC render hints and is the correct choice for
> categorical data — it picks the most common class value per output pixel rather than averaging.

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

A fixed HTML/CSS panel (bottom-left) listing the 12 LCM-10 classes with coloured swatches.
Colors are taken directly from the STAC `classification:classes` `color_hint` values.

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
   - Confirm bands, CRS, overviews, nodata=255 are reported correctly

5. **Build & deploy**
   ```bash
   npm run build   # outputs dist/
   ```
   Deploy `dist/` as a static site (GitHub Pages, Netlify, etc.)

---

## Key Dependencies

| Package | Version | Purpose |
|---|---|---|
| `maplibre-gl` | `^4.0` | Map engine + globe projection |
| `vite` | `^5` | Build tool |

---

## Open Questions / Risks

| Item | Notes |
|---|---|
| titiler rate limits | Public instance may throttle at scale. Self-host if needed. |
| S3 COG accessibility | `vito-lcf-shapefiles-waw4-1.s3.waw4-1.cloudferro.com` responds HTTP 200 with `accept-ranges: bytes` — range requests confirmed working. |
| Terrascope COG (auth) | Terrascope overview endpoint requires OIDC auth (HTTP 401). Individual 3×3 degree tiles also require auth. Public S3 mirror is the correct source for unauthenticated access. |
| titiler `bidx=1&bidx=2` + colormap | Need to confirm titiler applies colormap to band 1 and uses band 2 as alpha in the same request. May need `&return_mask=true` instead. |
| Nodata=255 vs alpha | The alpha band handles ocean masking cleanly. Nodata value 255 in band 1 falls outside the colormap and will render as transparent via the alpha mask — no extra `nodata` param needed in titiler. |
| Globe projection in MapLibre | Verify no breaking API changes in latest MapLibre 4.x release. |
| Zoom ceiling | STAC render hints specify zoom 6–14 for EPSG:3857. Tiles beyond z=14 should be avoided (no data overviews). |
