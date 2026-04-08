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
