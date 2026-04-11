# Plan: LCM-10 Enhancements

## 1. Higher-resolution tiles (titiler @2x)

### Background

PR #7 (`e10956a`) fixed a resolution mismatch by setting `tileSize: 256` to match
titiler's default 256×256 tile output. Before that fix, the source was configured with
`tileSize: 512` but the tile URL (`WebMercatorQuad/{z}/{x}/{y}`) only returned 256px
tiles — MapLibre stretched each tile to fill a 512px slot, causing blurry rendering.

### Enhancement

titiler supports a retina/high-DPI endpoint that returns genuine 512×512 tiles:

```
WebMercatorQuad@2x/{z}/{x}/{y}
```

Pairing this with `tileSize: 512` gives twice the pixel density with no stretching.

### Change required

In `html/globe_maplibre.html`, update the `LCM10_TILES` constant:

```js
// Before (256px tiles):
const LCM10_TILES =
  'https://titiler.xyz/cog/tiles/WebMercatorQuad/{z}/{x}/{y}'
  + `?url=${COG_URL}&bidx=1&colormap=${COLORMAP}`;

// After (512px tiles):
const LCM10_TILES =
  'https://titiler.xyz/cog/tiles/WebMercatorQuad@2x/{z}/{x}/{y}'
  + `?url=${COG_URL}&bidx=1&colormap=${COLORMAP}`;
```

And update the source config:

```js
map.addSource('lcm10', {
  type: 'raster',
  tiles: [LCM10_TILES],
  tileSize: 512,   // was 256 — must match @2x output
  // ...
});
```

### Considerations

- Each tile is 4× the pixel count (512² vs 256²) — higher bandwidth per tile.
  At global zoom levels this is a modest increase; at regional zoom it may be noticeable.
- The public `titiler.xyz` instance may apply rate limits; self-hosting via Docker
  removes that concern (`docker run -p 8000:8000 ghcr.io/developmentseed/titiler:latest`).
- The COG at CloudFerro S3 has internal overviews, so titiler will still read the
  appropriate overview level for each zoom — no wasted fetches.
