# Claude Code Instructions

## Globe Visualizations (Cesium, MapLibre)

Whenever you create or modify an HTML globe visualization file (e.g. any `*.html` file using Cesium or MapLibre GL JS), **always generate a GitHack preview link** after committing.

### How to generate the preview link

1. After committing, get the full commit SHA:
   ```bash
   git rev-parse HEAD
   ```

2. Construct the preview URL using the SHA (not a branch name) to avoid CDN caching:
   ```
   https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/<full-sha>/html/<filename>.html
   ```

3. Output the link to the user so they can open it directly in a browser.

### Example

```
Preview: https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/32ba1b1f8c.../html/globe_maplibre.html
```

### Why GitHack with a SHA?

- GitHack serves raw GitHub files with correct MIME types (unlike `raw.githubusercontent.com`), making HTML files render properly in the browser.
- Using the commit SHA instead of a branch name (`main`) bypasses GitHack's CDN cache, ensuring the preview always reflects the exact committed state.
