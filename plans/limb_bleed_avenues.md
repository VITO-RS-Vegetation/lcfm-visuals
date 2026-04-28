# Orthographic globe — limb fringe / bleed: fix avenues

## Resolved: two distinct artifacts at the disc edge

The "bleed/ring" is actually two separate effects stacked on top of each other. Misdiagnosing as one caused several failed attempts:

| # | Artifact | Visible as | Root cause | Fix |
|---|---|---|---|---|
| **A** | **Black ring**, 1–3 px wide, around the disc | Hard dark circle, present even with no bg COG, no coastlines, no borders | Cartopy strokes the orthographic boundary spine (`ax.spines['geo']`) with default `edgecolor='black'`, `linewidth ≈ 1pt` | **Option 0** below — `ax.spines['geo'].set_edgecolor('none')` |
| **B** | **Whitish/colour halo**, sub-pixel, only on the bottom/coloured half | Faint light fringe (Sahara → sand-coloured rim, ocean → near-invisible dark rim) | Cartopy reprojects the bg COG with bilinear interpolation; rim pixels are partial-alpha blends of bg colour and the transparent figure facecolor | **Option 3** below — alpha-threshold the saved PNG via PIL |

Both fixes are independent and complementary; the final solution applies them together.

## Fix avenues

Tried-and-rejected approaches are crossed out / marked INSUFFICIENT.

### 0. Hide the orthographic boundary spine — **CHOSEN (fixes artifact A)**

```python
ax.spines['geo'].set_edgecolor('none')
# legacy Cartopy fallback:
# ax.outline_patch.set_edgecolor('none')
```

- **Pros**: directly removes the actual artifact; preserves PNG transparency; one-line change. The spine still clips the axes content; only its visible stroke is suppressed.
- **Cons**: none observed.
- **Status**: applied. Removes the dark ring entirely.

### 3. Post-process saved PNG — threshold the alpha channel — **CHOSEN (fixes artifact B)**

Load the saved PNG with PIL, threshold its alpha channel to a hard binary mask (`alpha = np.where(alpha >= 128, 255, 0)`), and re-save in place.

- **Pros**: deterministic; preserves PNG transparency outside the disc; ~10 lines of code; no dependence on Cartopy AA internals.
- **Cons**: hard pixel-aligned limb (no AA at all). Imperceptible at icon size (256 px) and the 2100 px main globe size.
- **Status**: applied as `_snap_png_alpha()` after every transparent `fig.savefig`. Cleans the bilinear partial-alpha rim left by the bg COG warp.

### 1. Disable AA on the orthographic boundary spine — INSUFFICIENT

```python
ax.spines['geo'].set_antialiased(False)
```

- **Status**: tried — only sharpens the spine *stroke*, doesn't remove it. Superseded by option 0.

### 2. Render with an opaque dark-ocean figure facecolor — INSUFFICIENT

Replace `BACKGROUND = "transparent"` with an opaque dark-ocean colour so AA at the rim blends to ocean.

- **Status**: tried, reverted — spine stroke remained, PNG lost its transparent corners, and any non-abyssal disc area still showed a contrast band.

### 4. Render at 2× then downsample with explicit hard-mask alpha

- **Status**: not needed once options 0 + 3 work together. Keep as last resort if higher-quality limb AA is ever required.

### 5. Set boundary to a slightly inset circle + disable AA

- **Status**: variant of option 1. Not needed.

### ~~A. Alpha-mask the bg raster to the visible hemisphere~~ — DOES NOT WORK

- **Why it failed**: introduces a wider semi-transparent ring; reverted.

### ~~B. Set axes facecolor to opaque deep ocean RGBA~~ — DOES NOT WORK

- **Why it failed**: only affects what's behind the bg image inside the disc; both real artifacts (spine stroke and bilinear rim) are drawn on top.

## Lessons learned

- When debugging visual artifacts, sample actual pixel colours/alphas at suspected edges before theorising. Several rounds were wasted because "it looks like background bleed" became the working hypothesis without checking that the visible ring was actually solid black, not partial-alpha ocean.
- Cartopy's orthographic GeoAxes adds a default-stroked boundary spine even when no styling is requested. Always set `ax.spines['geo'].set_edgecolor('none')` for clean compositing.
- A bilinear-warped raster on transparent canvas always produces a partial-alpha rim; an alpha threshold post-process is the cheapest robust cleanup.
