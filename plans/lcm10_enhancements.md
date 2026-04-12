# Plan: LCM-10 Visual Quality Enhancements

## Problem: pixelation at low zoom levels

At global and continental zoom levels (z ≤ 4), the LCM-10 layer looks coarse and
blocky. Each rendered pixel represents a large geographic area and the colour
boundaries are jagged, making individual land-cover classes hard to distinguish.
**This is not a colour-blending or GPU-interpolation issue — it is a source-pixel
density problem.**

### Root cause: overview resolution vs. tilesize

The COG has internal overviews at reduction factors 2, 4, 8, 16, 32, 64, 128.
titiler selects the coarsest overview whose native pixel size is still finer than
the required output resolution:

```
required_geo_res = tile_geographic_width / tilesize
→ select overview where overview_res ≤ required_geo_res
```

With the current `tilesize=512` and `tileSize: 512` in MapLibre:

| zoom | tiles (WebMercator) | tile width | required geo res | overview used | overview width | pixel ≈ km |
|------|--------------------:|:----------:|:----------------:|:-------------:|:--------------:|:-----------:|
| 0    | 1×1                 | 360°       | 0.70°/px         | ov-64 (562px) | 562 px         | ≈ 78 km     |
| 1    | 2×2                 | 180°       | 0.35°/px         | ov-32 (1125px)| 562 px/tile    | ≈ 35 km     |
| 2    | 4×4                 | 90°        | 0.18°/px         | ov-16 (2250px)| 562 px/tile    | ≈ 17 km     |
| 3    | 8×8                 | 45°        | 0.088°/px        | ov-8 (4500px) | 562 px/tile    | ≈ 8.5 km    |
| 4    | 16×16               | 22.5°      | 0.044°/px        | ov-4 (9000px) | 562 px/tile    | ≈ 4.3 km    |
| 5    | 32×32               | 11.25°     | 0.022°/px        | ov-2 (18000px)| 562 px/tile    | ≈ 2.1 km    |
| 6    | 64×64               | 5.6°       | 0.011°/px        | native (36000px)| 562 px/tile  | ≈ 1.1 km    |

Notice that regardless of zoom, each tile gets roughly **562 source pixels** because
titiler picks the next-coarser overview as zoom decreases. To get more source pixels
per tile — and therefore less pixelation — tilesize must be increased.

---

## Enhancement A — Increase tilesize to 1024 (recommended quick win)

### Mechanics

Doubling `tilesize` from 512 → 1024 forces titiler to read the next-finer overview at
every zoom level, because the output requires twice as many pixels for the same
geographic area:

| zoom | overview (old 512) | overview (new 1024) | source px/tile | pixel ≈ km |
|------|:------------------:|:-------------------:|:--------------:|:-----------:|
| 0    | ov-64 (562 px)     | ov-32 (1125 px)     | 1125 px        | ≈ 32 km     |
| 1    | ov-32 (562 px)     | ov-16 (1125 px)     | 1125 px        | ≈ 16 km     |
| 2    | ov-16 (562 px)     | ov-8  (1125 px)     | 1125 px        | ≈ 8 km      |
| 3    | ov-8  (562 px)     | ov-4  (1125 px)     | 1125 px        | ≈ 4 km      |
| 4    | ov-4  (562 px)     | ov-2  (1125 px)     | 1125 px        | ≈ 2 km      |

Result: **every zoom level shows the source detail that was previously one zoom
level deeper**, with ~2× finer pixel resolution per linear dimension (4× area).

### Bandwidth cost

Each tile is 1024² instead of 512² PNG. A typical LCM-10 PNG tile is ~20–60 KB.
Doubling the pixel dimensions roughly doubles the compressed byte size (categorical
data compresses well), so expect **~1.5–2× bandwidth per tile**. The number of tiles
requested by MapLibre/Cesium stays the same — the total page load increase is
proportional to individual tile file size growth, not 4×.

### Code changes

**`html/globe_maplibre.html`**

```js
// Tile URL — change tilesize= parameter
const LCM10_TILES =
  'https://titiler.xyz/cog/tiles/WebMercatorQuad/{z}/{x}/{y}'
  + `?url=${COG_URL}&bidx=1&colormap=${COLORMAP}&tilesize=1024`;  // was 512

// MapLibre source — match tileSize to tile pixel dimensions
map.addSource('lcm10', {
  type: 'raster',
  tiles: [LCM10_TILES],
  tileSize: 1024,   // was 512
  attribution: '...',
});
```

**`html/globe_cesium.html`**

```js
viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
  url: `https://titiler.xyz/cog/tiles/WebMercatorQuad/{z}/{x}/{y}`
     + `?url=${COG_URL}&bidx=1&colormap=${COLORMAP}&tilesize=1024`,  // was 512
  tilingScheme: new Cesium.WebMercatorTilingScheme(),
  tileWidth:  1024,   // was 512
  tileHeight: 1024,   // was 512
  minimumLevel: 0,
  maximumLevel: 12,
  credit: new Cesium.Credit('...'),
}));
```

### Caveats

- Public `titiler.xyz` may rate-limit large tile requests. If timeouts appear,
  self-host: `docker run -p 8000:8000 ghcr.io/developmentseed/titiler:latest`.
- At z=0, the single tile spans the full world: titiler reads 1125px from overview-32
  and scales it into 1024px of output — still coarse, but noticeably better than 562px.
- At z ≥ 6, native COG resolution is reached regardless of tilesize; no visual
  difference above this zoom.

---

## Enhancement B — tilesize=2048 (aggressive, low-zoom focus)

Using `tilesize=2048` shifts the overview selection by **two levels** relative to the
current baseline:

| zoom | overview (current 512) | overview (2048) | pixel ≈ km |
|------|:----------------------:|:---------------:|:-----------:|
| 0    | ov-64 (562 px)         | ov-16 (2250 px) | ≈ 16 km     |
| 1    | ov-32 (562 px)         | ov-8  (2250 px) | ≈ 8 km      |
| 2    | ov-16 (562 px)         | ov-4  (2250 px) | ≈ 4 km      |

Global view (z=1) improves from ≈35 km/px to ≈8 km/px — **4× more source pixels
per dimension**, substantially reducing the blocky appearance.

**Downside:** individual tile PNGs are 4× the area of current tiles. Bandwidth
roughly doubles again vs. Enhancement A. For a typical globe at z=1–3, only 4–64
tiles are on screen, so the absolute traffic is still manageable (≤ ~20 MB), but
initial load time increases.

A sensible middle ground is to use `tilesize=2048` only for z ≤ 2 (where blockiness
is most obvious) and `tilesize=1024` for z 3–5. This requires either two separate
MapLibre sources (selected via `minzoom`/`maxzoom`) or dynamic URL rewriting — see
Enhancement C.

---

## Enhancement C — Zoom-adaptive tilesize (best quality/bandwidth ratio)

Use two tile sources in MapLibre, each active over a different zoom range:

```js
// Low-zoom source (z 0–2): large tiles for maximum source-pixel density
map.addSource('lcm10-lo', {
  type: 'raster',
  tiles: [
    `https://titiler.xyz/cog/tiles/WebMercatorQuad/{z}/{x}/{y}`
    + `?url=${COG_URL}&bidx=1&colormap=${COLORMAP}&tilesize=2048`,
  ],
  tileSize: 2048,
  minzoom: 0,
  maxzoom: 2,
});
map.addLayer({ id: 'lcm10-lo', type: 'raster', source: 'lcm10-lo', minzoom: 0, maxzoom: 3 });

// High-zoom source (z 3+): smaller tiles, still better than baseline
map.addSource('lcm10-hi', {
  type: 'raster',
  tiles: [
    `https://titiler.xyz/cog/tiles/WebMercatorQuad/{z}/{x}/{y}`
    + `?url=${COG_URL}&bidx=1&colormap=${COLORMAP}&tilesize=1024`,
  ],
  tileSize: 1024,
  minzoom: 3,
  maxzoom: 12,
});
map.addLayer({ id: 'lcm10-hi', type: 'raster', source: 'lcm10-hi', minzoom: 3 });
```

**Note:** MapLibre `minzoom`/`maxzoom` on the source controls which zoom levels
populate the tile cache; the layer `minzoom`/`maxzoom` controls visibility. Setting
a 1-zoom overlap on the layer (source `maxzoom: 2`, layer `maxzoom: 3`) lets
MapLibre keep the low-zoom tiles visible during the z=2→3 transition, preventing
a flash of blank space.

---

## Enhancement D — PMTiles pre-rendered tile cache (best long-term quality)

Pre-generating a static tile cache removes titiler entirely from the critical path,
allows full control over the resampling pipeline at each overview level, and
eliminates rate-limit concerns.

### Approach

1. **Generate tiles with rio-tiler / cogeo-mosaic**:
   - Read COG, render each z/x/y tile using mode resampling for categorical accuracy
   - Apply the 13-class colormap server-side
   - Pack into a PMTiles archive (single-file, HTTP range-request served)

2. **Host PMTiles**:
   - Any static file host works (GitHub Releases, Cloudflare R2, S3)
   - MapLibre + Cesium both support PMTiles natively (via `pmtiles://` protocol)

3. **Key benefit**: At each zoom level, the overview can be built with dedicated
   categorical-mode resampling from the full-resolution source, rather than relying
   on titiler's default. This is the only way to guarantee that small classes
   (mangroves, built-up, permanent water) are faithfully represented at z=0–2.

### Implementation outline

```bash
# Install
pip install cogeo-mosaic rio-tiler pmtiles

# Generate XYZ tile set (z 0–8)
python generate_lcm10_tiles.py  # custom script: iterates z/x/y, calls rio-tiler, writes PNG

# Pack into PMTiles
pmtiles convert output_tiles/ lcm10.pmtiles
```

**Estimated effort:** 1–2 days including tile generation (~15 min on a single machine
for z0–z8) and integration testing.

---

## Recommendation

| Priority | Enhancement | Effort | Visual gain |
|----------|-------------|--------|-------------|
| 1 (ship now) | A — tilesize=1024 | ~10 min, 4 line changes | **2× less blocky** at all zooms ≤ 5 |
| 2 (follow-up) | C — zoom-adaptive tilesize | ~1 h | **4× less blocky** at z ≤ 2, 2× at z 3–5 |
| 3 (future) | D — PMTiles | 1–2 days | Best achievable quality; no rate limits |

Start with **Enhancement A** for an immediate improvement, then evaluate whether
Enhancement C's complexity is warranted based on how the visualization looks after A.

---

## Note on the previous `@2x` enhancement

An earlier version of this document proposed switching to
`WebMercatorQuad@2x/{z}/{x}/{y}` (retina endpoint). This was written when the tile
URL used the default 256px tile size. Since `tilesize=512` is **already set** in the
current URL, the `@2x` path suffix would not change overview selection — titiler
selects overviews based on `geographic_extent / tilesize`, which is the same
regardless of the endpoint variant. The `@2x` suffix only affects the *default*
output resolution (256 → 512) when no explicit `tilesize` parameter is provided.
The `tilesize` parameter supersedes it, so the `@2x` change is a no-op under the
current URL construction.
