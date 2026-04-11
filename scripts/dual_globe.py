#!/usr/bin/env python3
"""Static dual-globe image using Cartopy + Matplotlib.

Renders the LCM-10 land cover map across 2 (or 3) orthographic globe views
side-by-side and saves a single PNG.  No local data file required: the script
reads the public Cloud-Optimized GeoTIFF directly over HTTPS, fetching only
the pre-built overview level at the requested downsample factor.

Dependencies (add to pyproject.toml):
    cartopy>=0.23  rasterio  matplotlib  numpy

Usage::

    python scripts/dual_globe.py

Outputs: dual_globe.png  (or the path set in OUTPUT_PATH)

Note: if the remote COG server uses a self-signed certificate, GDAL will
refuse the connection.  Work around it with::

    GDAL_HTTP_UNSAFESSL=YES python scripts/dual_globe.py
"""

from __future__ import annotations

import warnings
from pathlib import Path

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.enums import Resampling

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Public Cloud-Optimized GeoTIFF — HTTP range requests confirmed working.
# Override with a local path string if you have the file on disk.
COG_URL = (
    "https://vito-lcf-shapefiles-waw4-1.s3.waw4-1.cloudferro.com/"
    "LCM-10_v100_2020_MAP_lat-lon.tif"
)

# Downsample factor relative to native resolution (36 000 × 14 275).
# The script will read the pre-built COG overview that matches this factor
# exactly (no resampling).  If no exact match exists a warning is emitted
# and Resampling.mode (majority vote) is used as fallback.
# Factor 8  → ~4 500 × 1 784 px — sufficient for 300 DPI output.
DOWNSAMPLE_FACTOR: int = 8

OUTPUT_PATH = Path("dual_globe.png")

# "black" | "white" | "transparent"
BACKGROUND = "black"

# Number of globe panels.  Either 2 or 3.
N_GLOBES = 2

# (central_longitude, central_latitude) for each globe panel.
# 2-globe default: Western Hemisphere + Eastern Hemisphere.
GLOBE_CENTERS: list[tuple[float, float]] = [(-90.0, 0.0), (20.0, 0.0)]
# For a 3-globe layout emphasising Asia/Oceania, use:
#   GLOBE_CENTERS = [(-100.0, 0.0), (20.0, 0.0), (110.0, 0.0)]

COASTLINE_COLOR = "white"   # set to "black" for light backgrounds
COASTLINE_WIDTH = 0.4

DPI = 300
FIG_WIDTH_PER_GLOBE = 7.0   # inches; total figure width = N_GLOBES × this
FIG_HEIGHT = 7.0             # inches

# ---------------------------------------------------------------------------
# LCM-10 colormap  (value → CSS hex; None = transparent / no-data)
# ---------------------------------------------------------------------------
COLORMAP_HEX: dict[int, str | None] = {
    10:  "#006400",   # Tree cover
    20:  "#FFBB22",   # Shrubland
    30:  "#FFFF4C",   # Grassland
    40:  "#F096FF",   # Cropland
    50:  "#0096A0",   # Herbaceous wetland
    60:  "#00CF75",   # Mangroves
    70:  "#FAE6A0",   # Moss and lichen
    80:  "#B4B4B4",   # Bare / sparse vegetation
    90:  "#FA0000",   # Built-up
    100: "#0064C8",   # Permanent water bodies
    110: "#F0F0F0",   # Snow and ice
    254: "#0A0A0A",   # Unclassifiable
    255: None,        # No-data → transparent
}

# ---------------------------------------------------------------------------


def _hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    """Parse a CSS hex colour string to an (R, G, B, A) uint8 tuple."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r, g, b, alpha


def apply_colormap(
    band: np.ndarray,
    alpha_band: np.ndarray,
    colormap: dict[int, str | None],
) -> np.ndarray:
    """Map a uint8 categorical raster to an RGBA (H, W, 4) uint8 array.

    Args:
        band: 2-D uint8 array of land cover class values.
        alpha_band: 2-D uint8 array; 0 = no-data / transparent.
        colormap: mapping from class value to CSS hex string (or None).

    Returns:
        RGBA numpy array of shape (H, W, 4), dtype uint8.
    """
    rgba = np.zeros((*band.shape, 4), dtype=np.uint8)
    for val, color in colormap.items():
        if color is None:
            continue  # leave as transparent (alpha stays 0)
        mask = band == val
        rgba[mask] = _hex_to_rgba(color)
    # Honour the COG alpha band: no-data pixels become fully transparent.
    rgba[alpha_band == 0, 3] = 0
    return rgba


def load_data(cog_url: str, downsample: int) -> np.ndarray:
    """Open the COG and return an RGBA (H, W, 4) uint8 array.

    Reads a pre-built overview level when ``downsample`` exactly matches one
    of the COG's overview decimation factors.  Falls back to Resampling.mode
    with a warning otherwise.

    Args:
        cog_url: HTTPS URL or local path to the Cloud-Optimized GeoTIFF.
        downsample: Integer decimation factor (e.g. 8 → 1/8 resolution).

    Returns:
        RGBA array ready for ``ax.imshow``.
    """
    print(f"Opening COG: {cog_url}")
    with rasterio.open(cog_url) as src:
        overviews = src.overviews(1)  # decimation factors, e.g. [2, 4, 8, 16]
        print(f"  native size : {src.width} × {src.height}")
        print(f"  overviews   : {overviews}")

        ov_h = src.height // downsample
        ov_w = src.width  // downsample
        target_shape = (src.count, ov_h, ov_w)

        if downsample in overviews:
            print(f"  reading overview ×{downsample} ({ov_w} × {ov_h}) — no resampling")
            data = src.read(out_shape=target_shape)
        else:
            warnings.warn(
                f"No COG overview at factor {downsample}. "
                f"Available: {overviews}. "
                "Falling back to MODE resampling (slow for large files).",
                stacklevel=2,
            )
            data = src.read(out_shape=target_shape, resampling=Resampling.mode)

    band      = data[0]                          # categorical land cover (uint8)
    alpha_band = data[1] if data.shape[0] > 1 else np.full_like(band, 255)

    print(f"  applying colormap ...")
    rgba = apply_colormap(band, alpha_band, COLORMAP_HEX)
    print(f"  done — RGBA shape {rgba.shape}")
    return rgba


def build_figure(
    rgba: np.ndarray,
    globe_centers: list[tuple[float, float]],
    background: str,
    fig_w_per_globe: float,
    fig_h: float,
    coastline_color: str,
    coastline_width: float,
) -> plt.Figure:
    """Compose the multi-panel globe figure.

    Args:
        rgba: RGBA (H, W, 4) uint8 array covering [-180, 180] × [-90, 90].
        globe_centers: List of (central_lon, central_lat) for each panel.
        background: ``"black"``, ``"white"``, or ``"transparent"``.
        fig_w_per_globe: Width per globe panel in inches.
        fig_h: Figure height in inches.
        coastline_color: Edge colour for coastline features.
        coastline_width: Line width for coastline features.

    Returns:
        Configured :class:`matplotlib.figure.Figure`.
    """
    n = len(globe_centers)
    fig_w = fig_w_per_globe * n

    # Background colour for the figure and axes.
    if background == "transparent":
        bg_rgba = (0.0, 0.0, 0.0, 0.0)
    elif background == "white":
        bg_rgba = (1.0, 1.0, 1.0, 1.0)
    else:  # black (default)
        bg_rgba = (0.0, 0.0, 0.0, 1.0)

    fig = plt.figure(figsize=(fig_w, fig_h), facecolor=bg_rgba)

    for i, (lon, lat) in enumerate(globe_centers):
        proj = ccrs.Orthographic(central_longitude=lon, central_latitude=lat)
        ax = fig.add_subplot(1, n, i + 1, projection=proj)
        ax.set_facecolor(bg_rgba)

        # Render the land cover raster.  The full equirectangular extent is
        # [-180, 180] west→east and [-90, 90] south→north (origin='upper'
        # because the array rows run north→south).
        ax.imshow(
            rgba,
            origin="upper",
            extent=[-180, 180, -90, 90],
            transform=ccrs.PlateCarree(),
            interpolation="nearest",
            zorder=1,
        )

        ax.add_feature(
            cfeature.COASTLINE,
            linewidth=coastline_width,
            edgecolor=coastline_color,
            zorder=2,
        )

        ax.set_global()

    fig.subplots_adjust(left=0, right=1, bottom=0, top=1, wspace=0.02)
    return fig


def main() -> None:
    rgba = load_data(COG_URL, DOWNSAMPLE_FACTOR)

    if len(GLOBE_CENTERS) != N_GLOBES:
        raise ValueError(
            f"N_GLOBES={N_GLOBES} but GLOBE_CENTERS has {len(GLOBE_CENTERS)} entries."
        )

    print(f"Building {N_GLOBES}-globe figure (background={BACKGROUND!r}) ...")
    fig = build_figure(
        rgba=rgba,
        globe_centers=GLOBE_CENTERS,
        background=BACKGROUND,
        fig_w_per_globe=FIG_WIDTH_PER_GLOBE,
        fig_h=FIG_HEIGHT,
        coastline_color=COASTLINE_COLOR,
        coastline_width=COASTLINE_WIDTH,
    )

    transparent = BACKGROUND == "transparent"
    fig.savefig(
        OUTPUT_PATH,
        dpi=DPI,
        bbox_inches="tight",
        transparent=transparent,
        facecolor=fig.get_facecolor(),
    )
    plt.close(fig)
    print(f"Saved → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
