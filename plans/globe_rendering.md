# Globe rendering notes (Cartopy / Matplotlib)

Reference for [scripts/orthographic_globe.py](../scripts/orthographic_globe.py). Documents non-obvious requirements for clean orthographic globe PNGs on a transparent canvas.

## Disc-edge cleanup

Two distinct artifacts appear at the orthographic disc limb if not handled:

| Artifact | Cause | Fix in code |
|---|---|---|
| Black ring (1–3 px) around the disc, present even with no bg / no coastlines / no borders | Cartopy strokes the orthographic boundary spine (`ax.spines['geo']`) with `edgecolor='black'`, `linewidth ≈ 1pt` by default | `ax.spines['geo'].set_edgecolor('none')` (with `ax.outline_patch.set_edgecolor('none')` fallback for older Cartopy) — applied per panel inside `build_figure` |
| Whitish/colour halo at the rim, asymmetric (visible over light land like the Sahara, near-invisible over ocean) | Cartopy reprojects the bg COG with bilinear interpolation; rim pixels become partial-alpha blends of bg colour and the transparent figure facecolor | `_snap_png_alpha()` post-processes the saved PNG with PIL: thresholds the alpha channel to a hard binary mask (`alpha = np.where(alpha >= 128, 255, 0)`). Applied only when `transparent=True` |

Both fixes are independent and complementary. Always apply both for clean output on a transparent canvas.

## Approaches that do not work — do not retry

- **Alpha-mask the bg raster to the visible hemisphere** before plotting. Bilinear resampling of the masked alpha edge introduces a *wider* semi-transparent ring at the disc edge.
- **Set axes facecolor to an opaque deep-ocean RGBA**. Only affects what is behind the bg image inside the disc; the spine stroke and the bilinear rim are drawn on top.
- **Set figure facecolor opaque + save with `transparent=False`**. Removes the AA-against-transparency rim but the spine stroke is still visible, and the PNG loses its transparent corners.
- **Disable AA on the spine** (`ax.spines['geo'].set_antialiased(False)`). Sharpens the *stroke* but does not remove it.

## Debugging visual artifacts

Sample actual pixel colours/alphas at suspected edges before theorising. The spine-stroke ring was misdiagnosed as "background bleed" for several iterations because the working hypothesis was set without checking whether the visible ring was solid black or partial-alpha ocean.
