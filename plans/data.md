# Data Sources

Data used by the globe visualisation. See `GLOBE_VIZ_PLAN.md` for how these sources are wired into MapLibre.

---

## 1. Blue Marble — USGS Imagery

### WMS endpoint

**Service:** `https://basemap.nationalmap.gov/arcgis/services/USGSImageryOnly/MapServer/WMSServer`

| Property | Value |
|---|---|
| Protocol | WMS 1.1.1 and 1.3.0 |
| Layer | `0` |
| Format | `image/png` |

### Projection

| CRS | Status | Notes |
|---|---|---|
| `EPSG:3857` (WebMercator) | ✅ works | Strong polar distortion — avoid for globe texture |
| `EPSG:4326` (geographic) | ✅ works | Returns equirectangular image — preferred for sphere mapping |

### Verified WMS request (EPSG:4326, full-world)

```
https://basemap.nationalmap.gov/arcgis/services/USGSImageryOnly/MapServer/WMSServer
  ?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0
  &LAYERS=0&STYLES=&FORMAT=image/png
  &CRS=EPSG:4326&BBOX=-90,-180,90,180
  &WIDTH=256&HEIGHT=128
```

*Response: `image/png`, 60 KB — confirmed OK.*

Use `CRS=EPSG:4326` (WMS 1.3.0) or `SRS=EPSG:4326` (WMS 1.1.1). Axis order flips between WMS versions: 1.3.0 uses `minLat,minLon,maxLat,maxLon`.

### MapLibre tile endpoint

**Used in production — WMS 1.3.0, CRS=EPSG:3857:**

```js
map.addSource('blue-marble', {
  type: 'raster',
  tiles: [
    'https://basemap.nationalmap.gov/arcgis/services/USGSImageryOnly/MapServer/WMSServer'
    + '?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0'
    + '&LAYERS=0&STYLES=&FORMAT=image/png&TRANSPARENT=false'
    + '&CRS=EPSG:3857&WIDTH=256&HEIGHT=256'
    + '&BBOX={bbox-epsg-3857}',
  ],
  tileSize: 256,
  attribution: '© USGS',
});
```

MapLibre's `raster` source substitutes `{bbox-epsg-3857}` natively. Tiles are in WebMercator, which aligns perfectly with MapLibre's internal tile grid — no seams or reprojection artifacts.

**WMS version note:** `VERSION=1.3.0` uses `CRS=` for the projection parameter; `VERSION=1.1.x` uses `SRS=`. The USGS endpoint supports both.

#### Why not EPSG:4326?

MapLibre does **not** substitute `{bbox-epsg-4326}` — only `{bbox-epsg-3857}` is built-in. The literal string is forwarded to the WMS server, which returns HTTP 400.

A `maplibregl.addProtocol()` workaround was tested: it intercepts each tile request, computes an EPSG:4326 bounding box from the WebMercator tile coordinates, and fires a WMS 1.3.0 call with `CRS=EPSG:4326`. This eliminates the 400 error but introduces **projection seam artifacts** — the WMS returns equirectangular (lat/lon) images, but MapLibre positions them in WebMercator tile slots. At high latitudes (≥ ~60°N) the mismatch between the two projections is severe enough to create visible white slits at tile edges, especially near the antimeridian.

Conclusion: `addProtocol` + EPSG:4326 is not viable for tile-based display. EPSG:3857 with `{bbox-epsg-3857}` is the correct approach for MapLibre WMS raster sources. Polar coverage gaps (above ~85°N) are an imagery limitation of the USGS service, not a projection issue.

---

## 2. LCM-10 Land Cover Map

### Asset URLs

| Location | URL | Access |
|---|---|---|
| S3 / CloudFerro | `https://vito-lcf-shapefiles-waw4-1.s3.waw4-1.cloudferro.com/LCM-10_v100_2020_MAP_lat-lon.tif` | Public HTTPS, HTTP range requests confirmed (`accept-ranges: bytes`, HTTP 200) |
| Terrascope | `https://services.terrascope.be/download/LCFM/products/LCM-10/v100/overviews/LCM-10_v100_2020_MAP_lat-lon.tif` | Online but requires OIDC authentication (HTTP 401) |

The S3/CloudFerro URL is used in production.

### COG technical specification

| Property | Value |
|---|---|
| Format | Cloud-Optimized GeoTIFF (COG) |
| CRS | EPSG:4326 |
| Size | 36 000 × 14 275 px |
| Coverage | 180°W–180°E, 60°S–83°N |
| Band 1 | MAP — uint8, categorical land cover class |
| Band 2 | Alpha mask |
| No-data value | 255 (fully transparent; distinct from class 254 = Unclassifiable) |
| License | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| Attribution | © VITO 2026. European Union's Copernicus Land Monitoring Service information. [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

### Colormap

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
| 255 | No-data | transparent |

### Tiling via titiler

[titiler.xyz](https://titiler.xyz/) is a free public COG tile server. The browser requests standard XYZ tiles; titiler fetches the COG from S3 server-side. No CORS issues — the browser only talks to titiler.xyz.

#### Band selection

Combining `bidx=1&bidx=2` with `colormap` returns **HTTP 422 Unprocessable Content**. titiler's `colormap` parameter requires a single-band input; two bands produce a 2-channel output the colormap pipeline cannot process.

**Solution:** request only `bidx=1` and encode no-data (value 255) as fully transparent in the colormap:

```js
const COG_URL = encodeURIComponent(
  'https://vito-lcf-shapefiles-waw4-1.s3.waw4-1.cloudferro.com/LCM-10_v100_2020_MAP_lat-lon.tif'
);
const COLORMAP = encodeURIComponent(JSON.stringify({
  10:  [0,   100,   0, 255],   // Tree cover         #006400
  20:  [255, 187,  34, 255],   // Shrubland          #FFBB22
  30:  [255, 255,  76, 255],   // Grassland          #FFFF4C
  40:  [240, 150, 255, 255],   // Cropland           #F096FF
  50:  [0,   150, 160, 255],   // Herbaceous wetland #0096A0
  60:  [0,   207, 117, 255],   // Mangroves          #00CF75
  70:  [250, 230, 160, 255],   // Moss and lichen    #FAE6A0
  80:  [180, 180, 180, 255],   // Bare/sparse veg    #B4B4B4
  90:  [250,   0,   0, 255],   // Built-up           #FA0000
  100: [0,   100, 200, 255],   // Permanent water    #0064C8
  110: [240, 240, 240, 255],   // Snow and ice       #F0F0F0
  254: [10,   10,  10, 255],   // Unclassifiable     #0A0A0A
  255: [0,     0,   0,   0],   // No-data → transparent
}));

// XYZ tile URL template:
`https://titiler.xyz/cog/tiles/WebMercatorQuad/{z}/{x}/{y}?url=${COG_URL}&bidx=1&colormap=${COLORMAP}`
```

Verify COG access:
```
https://titiler.xyz/cog/info?url=<encoded-url>
```

#### Fallback: self-hosted titiler

If the public instance is insufficient (rate limits), self-host via Docker:

```bash
docker run -p 8000:8000 ghcr.io/developmentseed/titiler:latest
```

Replace `https://titiler.xyz` with `http://localhost:8000`.

---

## 3. LCM-10 STAC

**Collection:** [`lcfm-lcm-10`](https://stac.terrascope.be/collections/lcfm-lcm-10) on Terrascope STAC

The global mosaic COG is built from **2,647 individual 3×3 degree tiles**. Each tile is a single-band uint8 Cloud-Optimized GeoTIFF (~5–32 MB).

### Tile naming convention

```
LCFM_LCM-10_V100_2020_{LAT}{LON}_MAP.tif
```

### Example tile URL

```
https://services.terrascope.be/download/LCFM/products/LCM-10/v100/tiles_latlon/3deg/S60/W030/2020/LCFM_LCM-10_V100_2020_S60W030_MAP.tif
```

Authentication required (Terrascope OIDC).

### Coverage

- **Included:** 60°S–83°N (2,647 tiles)
- **Excluded:** Greenland ice cap fringe, High Arctic (>83°N), Antarctica (<60°S)

### Terrascope native titiler

`titiler.terrascope.be` supports a named `lcfm` colormap for tile previews but requires OIDC authentication. The public `titiler.xyz` instance with the explicit colormap above is used instead.

---

## 4. Country Borders — Natural Earth 50m

### Source

**Provider:** [Natural Earth](https://www.naturalearthdata.com/) — public domain cartographic dataset  
**Repository:** `nvkelso/natural-earth-vector` on GitHub  
**Scale:** 1:50 million (50m) — suitable for country-level zoom detail; a good balance between visual fidelity and file size

### GeoJSON URL

```
https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson
```

Served by `raw.githubusercontent.com` with `Access-Control-Allow-Origin: *` — no CORS issues in the browser.

### Technical notes

| Property | Value |
|---|---|
| Format | GeoJSON (Polygon/MultiPolygon features) |
| Scale | 1:50 million |
| Approx. file size | ~3–4 MB (one-time fetch, browser-cached) |
| Geometry type | Polygon / MultiPolygon (rendered as `line` in MapLibre) |
| License | Public domain |

Rendering polygon features as a MapLibre `line` type layer draws only the outlines — no fill — so the land-cover raster remains fully visible underneath. This also ensures island nations (Japan, Iceland, Philippines, etc.) get outlines, which a boundary-lines-only file would omit.

### Scale comparison

| Scale | File | Approx. size | Use case |
|---|---|---|---|
| 110m | `ne_110m_admin_0_countries.geojson` | ~360 KB | Global overview only |
| **50m** | `ne_50m_admin_0_countries.geojson` | ~3–4 MB | **Country-level zoom — used in production** |
| 10m | `ne_10m_admin_0_countries.geojson` | ~25 MB | Sub-national detail (may impact load time) |

### MapLibre layer config

```js
map.addSource('country-borders', {
  type: 'geojson',
  data: 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson',
});
map.addLayer({
  id: 'country-borders',
  type: 'line',
  source: 'country-borders',
  layout: {
    'line-join': 'round',
    'line-cap': 'round',
    'visibility': 'visible',   // toggled at runtime via setLayoutProperty
  },
  paint: {
    'line-color': '#000000',   // black — visible over all LCM-10 palette colours
    'line-width': 0.7,
    'line-opacity': 0.55,
  },
});
