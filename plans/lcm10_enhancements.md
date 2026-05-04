# Plan: LCM-10 Visual Quality Enhancement

## Problem

At globe and continental zoom levels the LCM-10 categorical raster layer
appears pixelated. The cause is that `tilesize=512` causes titiler to select
a relatively coarse COG overview, yielding few source data pixels per display
pixel and hard nearest-neighbour class edges.

## Solution: 1024 px tiles with 512 px renderer slot

Use an **intentional mismatch** between the titiler tile size and the renderer
tile slot size:

| Parameter | Value | Reason |
|-----------|-------|--------|
| `tilesize=1024` (URL) | 1024 | titiler picks a 2× finer COG overview → ~2× source data per CSS pixel |
| `resampling=mode` (URL) | mode | dominant categorical class wins per pixel before colormap is applied |
| `tileSize: 512` (MapLibre source) | 512 | renderer requests tiles at z−1 equivalent; 1024 px rendered into 512 px slot → GPU bilinear 2:1 downsampling |
| `tileWidth/Height: 512` (Cesium) | 512 | same as above |

The GPU bilinear downsampling produces smooth colour transitions at class
boundaries, visually superior to hard-edged nearest-neighbour sampling at
low zoom levels.

The COG block size is 1024 px, so titiler reads ~1–2 COG blocks per tile
request (efficient S3 access). The overview pyramid (×2…×128) is identical
to a 512-block COG — block size only affects read efficiency, not overview
coverage.

Source density at any given display zoom level: ~2× more COG data per CSS
pixel compared to the matched `tilesize=512` / `tileSize: 512` baseline.

## Status: Implemented

Changes applied to:
- `html/globe_maplibre.html` — `LCM10_TILES` constant (`resampling=mode&tilesize=1024`)
- `html/globe_cesium.html` — `UrlTemplateImageryProvider` URL (`resampling=mode&tilesize=1024`)
