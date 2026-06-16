# Data: Terrascope MapProxy

Reference for using the Terrascope MapProxy service as a single tile source for the LCM-10 layer.

Source: https://docs.terrascope.be/Developers/WebServices/OGC/MapProxy.html

---

## Service endpoints

| Protocol | URL |
|---|---|
| WMTS | `https://mapproxy.terrascope.be/mapproxy/wmts/1.0.0/WMTSCapabilities.xml` |
| WMS | `https://mapproxy.terrascope.be/mapproxy/service?service=WMS&request=GetCapabilities` |

---

## LCM-10 layer: `LCM_2020`

| Property | Value |
|---|---|
| Layer identifier | `LCM_2020` |
| Description | LCM layer for 2020 |
| Spatial extent | [-180.0, -85.1, 180.0, 85.1] |
| Temporal extent | (none listed — static 2020 product) |
| Relation to existing layer | Same product as `lcfm-lcm-10_map` on `wmts.terrascope.be` — different identifier |

### Comparison with current tile sources

| Property | titiler.xyz (current low-zoom) | wmts.terrascope.be (current high-zoom) | MapProxy (proposed) |
|---|---|---|---|
| Zoom range | All zooms (COG-derived) | z6–z14 only | All zooms (pre-rendered cache) |
| Tile size | 256 px (or 512 px @2x) | 256 px | TBC from capabilities |
| Auth | None | None | Possibly required — see below |
| Third-party dependency | Yes (titiler.xyz) | No | No |
| Zoom-switching logic required | Yes (paired with WMTS) | Yes (paired with titiler) | **No — single source** |
| Rate limits | Yes (public instance) | Unknown | Unknown |

MapProxy is described by Terrascope as optimal for exactly this use case:
> "The MapProxy service is particularly useful when you need to visualise products at high zoom levels with smooth overview transitions."

---

## Authentication

Public layers require no authentication. Restricted layers require OAuth2 using the Resource Owner Password Credentials (ROPC) grant flow.

**`LCM_2020` auth status: to be verified** (see Phase 1 below).

### OAuth2 ROPC token request

```
POST https://sso.terrascope.be/auth/realms/terrascope/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded

grant_type=password
&client_id=public
&username=<terrascope-username>
&password=<terrascope-password>
```

Response includes `access_token` (JWT) and `expires_in` (seconds).

### Using the token in tile requests

```
Authorization: Bearer <access_token>
```

Add this header to every tile HTTP request. The token must be refreshed before expiry (typically 300 s — confirm from `expires_in`).

---

## Tile URL formats

### WMTS KVP GetTile (most portable, confirmed working for `wmts.terrascope.be`)

```
https://mapproxy.terrascope.be/mapproxy/service
  ?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0
  &LAYER=LCM_2020
  &STYLE=default
  &FORMAT=image/png
  &TILEMATRIXSET=<tileMatrixSet>
  &TILEMATRIX={z}
  &TILEROW={y}
  &TILECOL={x}
```

Exact `TILEMATRIXSET` identifier must be confirmed from capabilities. Likely `EPSG:3857` or `GoogleMapsCompatible`.

### WMTS REST template (typical MapProxy pattern)

```
https://mapproxy.terrascope.be/mapproxy/wmts/LCM_2020/default/{TileMatrixSet}/{TileMatrix}/{TileRow}/{TileCol}.png
```

> **Note**: the REST template published by `wmts.terrascope.be` for `lcfm-lcm-10_map` was found to return HTTP 400 in previous testing (see `wms_wmts_findings.md`). Verify whether the MapProxy REST template is usable before relying on it.

---

## Open items — Phase 1 verification steps

These must be confirmed before any code changes.

1. **Fetch capabilities**: `GET https://mapproxy.terrascope.be/mapproxy/wmts/1.0.0/WMTSCapabilities.xml`
   - Confirm `LCM_2020` is listed
   - Record exact `TileMatrixSet` identifier(s)
   - Record supported zoom range (min/max `TileMatrix`)
   - Record tile format (`image/png` expected)

2. **Test unauthenticated tile** (z=3, any valid row/col):
   - HTTP 200 → layer is **public**, no auth needed
   - HTTP 401 or 403 → layer is **restricted**, OAuth2 required

3. **Test OAuth2 ROPC flow** (if needed):
   - POST to token endpoint with Terrascope credentials
   - Confirm `access_token` is returned
   - Re-request tile with `Authorization: Bearer <token>` header
   - Confirm HTTP 200

4. **Check CORS headers** on a tile response:
   - Confirm `Access-Control-Allow-Origin` is present
   - If absent and auth is required, a server-side proxy will be needed before the HTML viewers can use the layer

5. **Confirm `LCM_2020` = `lcfm-lcm-10_map`**:
   - Fetch one tile from each service at the same z/x/y
   - Visually compare — land cover classes should be identical

---

## Integration notes for viewers

### MapLibre (`globe_maplibre.html`)

Replace the current dual-source setup with a single `raster` source:

```js
map.addSource('lcm10', {
  type: 'raster',
  tiles: [
    'https://mapproxy.terrascope.be/mapproxy/service'
    + '?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0'
    + '&LAYER=LCM_2020&STYLE=default&FORMAT=image/png'
    + '&TILEMATRIXSET=EPSG:3857'   // confirm from capabilities
    + '&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}',
  ],
  tileSize: 256,   // confirm from capabilities
  attribution: '© VITO 2026. Copernicus Land Monitoring Service. CC-BY 4.0',
});
```

If auth is required, inject the Bearer token via `transformRequest`:

```js
map.transformRequest = (url, resourceType) => {
  if (resourceType === 'Tile' && url.startsWith('https://mapproxy.terrascope.be')) {
    return { url, headers: { Authorization: `Bearer ${accessToken}` } };
  }
};
```

### CesiumJS (`globe_cesium.html`)

Replace `UrlTemplateImageryProvider` (titiler.xyz) with the native WMTS provider:

```js
const lcm10 = new Cesium.WebMapTileServiceImageryProvider({
  url: 'https://mapproxy.terrascope.be/mapproxy/service',
  layer: 'LCM_2020',
  style: 'default',
  format: 'image/png',
  tileMatrixSetID: 'EPSG:3857',   // confirm from capabilities
  // If auth required:
  // Use Cesium.Resource with customRequestHeaders
});
```

### Flythrough recorder (`flythrough_recorder.py`)

If auth is required, acquire token before Playwright launch and inject via route interception:

```python
import os, requests

resp = requests.post(
    'https://sso.terrascope.be/auth/realms/terrascope/protocol/openid-connect/token',
    data={
        'grant_type': 'password',
        'client_id': 'public',
        'username': os.environ['TERRASCOPE_USER'],
        'password': os.environ['TERRASCOPE_PASS'],
    },
    timeout=10,
)
resp.raise_for_status()
token = resp.json()['access_token']

# In Playwright:
async def inject_auth(route):
    if 'mapproxy.terrascope.be' in route.request.url:
        headers = {**route.request.headers, 'Authorization': f'Bearer {token}'}
        await route.continue_(headers=headers)
    else:
        await route.continue_()

await page.route('**/*', inject_auth)
```

---

## Public deployment concern

The GitHub Pages live site is publicly accessible. If `LCM_2020` requires authentication, unauthenticated visitors will see no LCM-10 tiles. Options:

| Option | Trade-off |
|---|---|
| Accept — internal tool only | Simple; breaks public viewer |
| Keep `wmts.terrascope.be` (`lcfm-lcm-10_map`) as public fallback at z≥6 | Dual-source complexity remains for public builds |
| Request VITO to make `LCM_2020` public on MapProxy | Cleanest; requires external action |

Resolve this after Phase 1 confirms the auth requirement.
