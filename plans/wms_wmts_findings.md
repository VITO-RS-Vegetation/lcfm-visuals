# WMS / WMTS Service Findings

## 1. USGS Blue Marble — WMS background

**Endpoint:** `https://basemap.nationalmap.gov/arcgis/services/USGSImageryOnly/MapServer/WMSServer`

| Property | Value |
|---|---|
| Protocol | WMS 1.1.1 and 1.3.0 |
| Layer | `0` |
| Format | `image/png` |

### Projection options

| CRS | Status | Notes |
|---|---|---|
| `EPSG:3857` (WebMercator) | ✅ works | Has strong polar distortion / artefacts — avoid for globe texture |
| `EPSG:4326` (geographic) | ✅ works | Returns equirectangular image, **preferred** for sphere mapping |

### Verified request (EPSG:4326, full-world)

```
https://basemap.nationalmap.gov/arcgis/services/USGSImageryOnly/MapServer/WMSServer
  ?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0
  &LAYERS=0&STYLES=&FORMAT=image/png
  &CRS=EPSG:4326&BBOX=-90,-180,90,180
  &WIDTH=256&HEIGHT=128
```

*Response: `image/png`, 60 KB — confirmed OK.*

### Key point
Use `CRS=EPSG:4326` (WMS 1.3.0) or `SRS=EPSG:4326` (WMS 1.1.1) with `BBOX=<minLat,minLon,maxLat,maxLon>` (axis order flips between versions). For a full-world equirectangular texture, request the whole extent in one or a grid of tiles.

---

## 2. Terrascope — LCM-10 WMTS foreground

### 2a. WMTS service

**Capabilities endpoint:** `https://wmts.terrascope.be/?REQUEST=GetCapabilities&service=wmts`
(Verified on April 14, 2026 — HTTP 200, ~5.4 MB XML)

**Layer identifier:** `lcfm-lcm-10_map`

| Property | Value |
|---|---|
| Title | `lcfm-lcm-10_map` |
| Format | `image/png` |
| Style | `default` |
| Time dimension | `2020-01-01` (only value) |
| Bounding box | lon -180..180 · lat -60..83 |
| Tile matrix sets | `EPSG:3857` only (**no** EPSG:4326 / WorldCRS84Quad) |
| Zoom range | z6–z14 |

**KVP GetTile request (verified working):**
```
https://wmts.terrascope.be/wmts
  ?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0
  &LAYER=lcfm-lcm-10_map&STYLE=default&FORMAT=image/png
  &TILEMATRIXSET=EPSG:3857&TILEMATRIX=6&TILEROW=22&TILECOL=32
  &TIME=2020-01-01
```

*Response on April 14, 2026: `HTTP 200`, `content-type: image/png`, `content-length: 31304`.*

**REST tile URL template (published in capabilities):**
```
https://wmts.terrascope.be/lcfm-lcm-10/default/{TIME}/{TileMatrixSet}/{TileMatrix}/{TileCol}/{TileRow}.png
  ?assets=MAP&colormap_name=lcfm&resampling=mode
```

**TileMatrix identifiers:** `0`, `1`, `2`, … `14` (plain integers, not `EPSG:3857:7` style).

**TileMatrixSetLimits per zoom (valid tile rows/cols):**

| Zoom | MinRow | MaxRow | MinCol | MaxCol |
|------|--------|--------|--------|--------|
| 6 | 3 | 45 | 0 | 63 |
| 7 | 7 | 90 | 0 | 127 |
| 8 | 14 | 181 | 0 | 255 |
| 9 | 28 | 363 | 0 | 511 |
| 10 | 56 | 726 | 0 | 1023 |
| 11 | 113 | 1453 | 0 | 2047 |
| 12 | 226 | 2906 | 0 | 4095 |
| 13 | 452 | 5813 | 0 | 8191 |
| 14 | 905 | 11626 | 0 | 16383 |

### 2b. Connection / URL findings

| Request style | Result |
|---|---|
| KVP `GetTile` with `SERVICE=WMTS` | HTTP 200, returns `image/png` |
| REST URL template from capabilities | HTTP 400 |
| `GetMap` to `https://wmts.terrascope.be/` with `SERVICE=WMS` | HTTP 400 |
| `GetMap` to `https://wmts.terrascope.be/wmts` with `SERVICE=WMS` | HTTP 400 |

The capabilities-published REST template is not currently usable as-is. A live request on
April 14, 2026 returned:

```json
{"detail":"Missing WMTS 'SERVICE' parameter."}
```

Likewise, `wmts.terrascope.be` does not behave as a WMS endpoint for this layer. Live
`GetMap` attempts to both the root path and `/wmts` returned:

```json
{"detail":"Invalid 'SERVICE' parameter: WMS. Only 'wmts' is accepted"}
```

Practical conclusion: for public access to this layer, use the WMTS KVP `GetTile`
pattern rather than the published REST template or a WMS `GetMap` request.

### 2c. Terrascope WMS (`services.terrascope.be`)

**Endpoint:** `https://services.terrascope.be/wms/v2`

This host remains a plausible separate WMS source to check for LCM-10, but a capabilities
search on April 14, 2026 did **not** find the exact layer identifier `lcfm-lcm-10_map`.
That does **not** prove LCM-10 is absent from the service under all possible names; it
only means the known WMTS layer id was not advertised there.

---

## 3. Design implications for the globe

| Layer | Source | Projection issue | Plan |
|---|---|---|---|
| Blue Marble background | USGS WMS | EPSG:4326 available — no polar artefacts | Single `GetMap` request at high resolution for full-world equirectangular texture |
| LCM-10 foreground | Terrascope WMTS | Only EPSG:3857 — polar distortion up to ±85° lat | Option A: stitch WebMercator tiles + reproject to equirectangular (Python/PIL). Option B: look for a separately advertised Terrascope WMS layer under another name. Option C: overlay tiles dynamically in the browser (requires `THREE.TiledTexture` custom code or a canvas compositor). |

## 4. Open questions

1. **REST template behavior**: Is the published `ResourceURL` template misconfigured, or does it require an undocumented proxy path or query parameter?
2. **WMS alternative**: Does `https://services.terrascope.be/wms/v2` expose LCM-10 under a different layer name, or is there another Terrascope WMS host?
3. **Reprojection pipeline**: If tiles must be in EPSG:3857, should the builder script reproject them to EPSG:4326 using `rasterio`/`PIL` before compositing the final texture?
