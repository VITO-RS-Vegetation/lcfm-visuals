#!/usr/bin/env python3
"""Static orthographic globe image using Cartopy + Matplotlib.

Renders the LCM-10 land cover map across one or more orthographic globe panels
side-by-side and saves a single PNG.  No local data file required: the script
reads the public Cloud-Optimized GeoTIFF directly over HTTPS, fetching only
the pre-built overview level at the requested downsample factor.

Background imagery
------------------
By default the script uses a bathymetry/topography COG as the base layer,
visible in the polar regions outside the LCM-10 coverage extent (60°S – 83°N).
Set ``BG_COG_URL = None`` to fall back to Cartopy's built-in Natural Earth
shaded-relief image (``ax.stock_img()``).

Globe views
-----------
Each panel is described by a :class:`GlobeView` (lon, lat, optional zoom).
Views can be specified as explicit (lon, lat) pairs **or** parsed directly from
a MapLibre URL hash (``#zoom/lat/lng``).  When a zoom level is present the
panel renders a rectangular "screen view" matching what the MapLibre globe
would show at that camera position; without a zoom the full circular globe is
shown.

Pixel-based sizing
------------------
Output dimensions are controlled by ``GLOBE_SIZE_PX`` (each panel's square
side length) and ``GLOBE_GAP_PX`` (inter-panel gap; outer margins are half
this value on all four sides)::

    Figure width  = N × (GLOBE_SIZE_PX + GLOBE_GAP_PX) px
    Figure height =      GLOBE_SIZE_PX + GLOBE_GAP_PX  px

Config-driven batch rendering
------------------------------
Run with ``--config configs/globes.toml`` to execute all ``[[render]]`` entries
in the TOML file.  Each entry produces a separate output PNG.  Without
``--config`` the hardcoded module-level constants are used.

Country borders
---------------
Set ``COUNTRY_BORDERS = True`` to overlay country outlines from Natural Earth
(via Cartopy's built-in ``BORDERS`` feature).

Dependencies:
    cartopy>=0.23  rasterio  matplotlib  numpy

Usage::

    python scripts/orthographic_globe.py
    python scripts/orthographic_globe.py --config configs/globes.toml

Note: if the remote COG server uses a self-signed certificate, GDAL will
refuse the connection.  Work around it with::

    GDAL_HTTP_UNSAFESSL=YES python scripts/orthographic_globe.py
"""

from __future__ import annotations

import argparse
import math
import tomllib
import warnings
from dataclasses import dataclass
from pathlib import Path

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.enums import Resampling

# ---------------------------------------------------------------------------
# Globe view
# ---------------------------------------------------------------------------

@dataclass
class GlobeView:
    """Camera position for a single globe panel.

    Attributes:
        lon: Central longitude in degrees.
        lat: Central latitude in degrees.
        zoom: MapLibre zoom level.  ``None`` renders the full circular globe;
            a numeric value crops the panel as a rectangular "screen view"
            matching the MapLibre globe at that zoom.
    """

    lon: float
    lat: float
    zoom: float | None = None


# ---------------------------------------------------------------------------
# MapLibre helpers
# ---------------------------------------------------------------------------

def parse_maplibre_hash(url_or_hash: str) -> tuple[float, float, float]:
    """Parse a MapLibre URL or bare hash fragment and return (zoom, lat, lng).

    MapLibre hash order: ``#zoom/lat/lng[/bearing/pitch]``.
    Bearing and pitch are accepted but ignored.

    Args:
        url_or_hash: A full URL containing a ``#`` fragment, a bare hash
            string such as ``"#3.47/39.33/3.76"``, or just ``"3.47/39.33/3.76"``.

    Returns:
        ``(zoom, lat, lng)`` as floats.

    Raises:
        ValueError: If fewer than three slash-separated values are found.
    """
    fragment = url_or_hash.split("#")[-1].lstrip("#")
    parts = fragment.split("/")
    if len(parts) < 3:
        raise ValueError(
            f"MapLibre hash must contain at least zoom/lat/lng, got: {url_or_hash!r}"
        )
    return float(parts[0]), float(parts[1]), float(parts[2])


def zoom_to_mpp(zoom: float, lat: float) -> float:
    """Convert a MapLibre zoom level to metres per pixel at the given latitude.

    Uses standard WebMercator tile math (512-px tiles, equatorial
    circumference 40 075 016.68 m)::

        mpp = (40_075_016.68 / (512 × 2^zoom)) × cos(lat)

    Args:
        zoom: MapLibre zoom level (fractional values accepted).
        lat: Latitude in degrees (cosine-adjusted scale factor).

    Returns:
        Metres per pixel as a float.
    """
    return (40_075_016.68 / (512.0 * (2.0 ** zoom))) * math.cos(math.radians(lat))


def globe_view_from_maplibre_url(url_or_hash: str) -> GlobeView:
    """Create a :class:`GlobeView` from a MapLibre URL or hash fragment.

    Note: MapLibre hash order is ``zoom/lat/lng`` — lat and lng are swapped
    relative to the ``(lon, lat)`` convention used by the orthographic
    projection.  This function performs the swap automatically.

    Args:
        url_or_hash: A MapLibre URL containing a ``#`` fragment, or a bare
            hash string.

    Returns:
        A :class:`GlobeView` with ``lon``, ``lat``, and ``zoom`` set.
    """
    zoom, lat, lon = parse_maplibre_hash(url_or_hash)
    return GlobeView(lon=lon, lat=lat, zoom=zoom)


# ---------------------------------------------------------------------------
# Config constants  (edit these when running without --config)
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

# Optional background imagery COG (3-band RGB uint8, EPSG:4326).
# None → use Cartopy's built-in Natural Earth stock image (ax.stock_img()).
BG_COG_URL: str | None = (
    "https://vito-lcf-shapefiles-waw4-1.s3.waw4-1.cloudferro.com/"
    "world_topo_bathy_200407_WGS84.tif"
)
BG_DOWNSAMPLE_FACTOR: int = 8

OUTPUT_PATH = Path("orthographic_globe.png")

# "black" | "white" | "transparent"
BACKGROUND = "black"

# Globe panels.  N_GLOBES is derived dynamically from len(GLOBE_VIEWS).
# Use globe_view_from_maplibre_url() to create a GlobeView from a MapLibre
# URL hash instead of explicit (lon, lat) pairs.
GLOBE_VIEWS: list[GlobeView] = [GlobeView(-90.0, 15.0), GlobeView(60.0, 25.0)]

# Panel size and spacing in pixels.
# Each panel is GLOBE_SIZE_PX × GLOBE_SIZE_PX.
# GLOBE_GAP_PX is the gap between adjacent panels; outer margins equal
# GLOBE_GAP_PX / 2 on every side (left, right, top, bottom).
GLOBE_SIZE_PX: int = 2100
GLOBE_GAP_PX: int = 200

DPI: int = 300

# ---------------------------------------------------------------------------
# Coastlines and country borders
# ---------------------------------------------------------------------------
COASTLINES: bool = True
COUNTRY_BORDERS: bool = False
BORDER_COLOR: str = "white"   # use "black" for light backgrounds
BORDER_WIDTH: float = 0.4

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


def _read_overview(src: rasterio.DatasetReader, downsample: int,
                   resampling_fallback: Resampling,
                   bands: list[int] | None = None) -> np.ndarray:
    """Read ``src`` at 1/``downsample`` resolution, preferring a COG overview.

    If ``downsample`` exactly matches a pre-built overview level the data is
    returned without any resampling.  Otherwise ``resampling_fallback`` is
    applied and a :class:`UserWarning` is emitted.

    Args:
        src: Open rasterio dataset.
        downsample: Integer decimation factor.
        resampling_fallback: Resampling algorithm used when no exact overview
            match is found.
        bands: 1-based list of band indices to read.  ``None`` = all bands.

    Returns:
        Numpy array of shape ``(bands, H/downsample, W/downsample)``.
    """
    overviews = src.overviews(1)
    ov_h = src.height // downsample
    ov_w = src.width  // downsample
    kwargs: dict = {}
    if bands is not None:
        kwargs["indexes"] = bands
    target_shape = (len(bands) if bands else src.count, ov_h, ov_w)

    if downsample in overviews:
        print(f"  reading overview ×{downsample} ({ov_w} × {ov_h}) — no resampling")
        return src.read(out_shape=target_shape, **kwargs)

    warnings.warn(
        f"No COG overview at factor {downsample}. "
        f"Available: {overviews}. "
        f"Falling back to {resampling_fallback.name} resampling.",
        stacklevel=3,
    )
    return src.read(out_shape=target_shape, resampling=resampling_fallback, **kwargs)


def load_data(cog_url: str, downsample: int) -> tuple[np.ndarray, list[float]]:
    """Open the LCM-10 COG and return an RGBA (H, W, 4) array and its extent.

    Uses ``Resampling.mode`` as fallback (majority vote — correct for
    categorical data).

    Args:
        cog_url: HTTPS URL or local path to the Cloud-Optimized GeoTIFF.
        downsample: Integer decimation factor (e.g. 8 → 1/8 resolution).

    Returns:
        Tuple of (RGBA array, extent) where extent is
        ``[left, right, bottom, top]`` in degrees, read directly from the COG
        metadata (e.g. [-180, 180, -60, 83] for LCM-10).
    """
    print(f"Opening LCM-10 COG: {cog_url}")
    with rasterio.open(cog_url) as src:
        print(f"  native size : {src.width} × {src.height}")
        print(f"  overviews   : {src.overviews(1)}")
        b = src.bounds
        extent = [b.left, b.right, b.bottom, b.top]
        print(f"  extent      : {extent}")
        data = _read_overview(src, downsample, Resampling.mode)

    band       = data[0]
    alpha_band = data[1] if data.shape[0] > 1 else np.full_like(band, 255)

    print("  applying colormap ...")
    rgba = apply_colormap(band, alpha_band, COLORMAP_HEX)
    print(f"  done — RGBA shape {rgba.shape}")
    return rgba, extent


def load_background(cog_url: str, downsample: int) -> tuple[np.ndarray, list[float]]:
    """Open a background imagery COG and return an (H, W, 3) RGB array and extent.

    Reads only the first three bands (R, G, B).  Uses ``Resampling.bilinear``
    as fallback, which is appropriate for continuous imagery.

    Args:
        cog_url: HTTPS URL or local path to a 3-band uint8 EPSG:4326 COG.
        downsample: Integer decimation factor.

    Returns:
        Tuple of (RGB array, extent) where extent is
        ``[left, right, bottom, top]`` in degrees, read from the COG metadata.
    """
    print(f"Opening background COG: {cog_url}")
    with rasterio.open(cog_url) as src:
        print(f"  native size : {src.width} × {src.height}")
        print(f"  overviews   : {src.overviews(1)}")
        b = src.bounds
        extent = [b.left, b.right, b.bottom, b.top]
        print(f"  extent      : {extent}")
        data = _read_overview(src, downsample, Resampling.bilinear, bands=[1, 2, 3])

    rgb = np.moveaxis(data, 0, -1)  # (3, H, W) → (H, W, 3)
    print(f"  done — RGB shape {rgb.shape}")
    return rgb, extent


def build_figure(
    rgba: np.ndarray,
    lcm_extent: list[float],
    globe_views: list[GlobeView],
    background: str,
    globe_size_px: int,
    globe_gap_px: int,
    dpi: int = 300,
    bg_rgb: np.ndarray | None = None,
    bg_extent: list[float] | None = None,
    coastlines: bool = True,
    country_borders: bool = False,
    border_color: str = "white",
    border_width: float = 0.4,
    aspect_ratio: float = 1.0,
) -> plt.Figure:
    """Compose the multi-panel globe figure.

    Each panel is ``globe_size_px`` wide and ``globe_size_px / aspect_ratio``
    tall.  ``aspect_ratio = 1.0`` (default) gives square panels; ``1.78``
    gives 16:9, ``1.33`` gives 4:3, etc.
    ``globe_gap_px`` controls both the inter-panel gap and the outer margins
    (outer margins = ``globe_gap_px / 2`` on all four sides)::

        Figure width  = N × (globe_size_px + globe_gap_px) px
        Figure height =      (globe_size_px / aspect_ratio) + globe_gap_px  px

    When a :class:`GlobeView` carries a ``zoom`` value, the panel renders a
    rectangular "screen view" — the region visible in a MapLibre globe at
    that zoom level.  Without a zoom the full circular globe is shown.

    Args:
        rgba: RGBA (H, W, 4) uint8 LCM-10 array.
        lcm_extent: ``[left, right, bottom, top]`` in degrees for the LCM-10
            layer (e.g. ``[-180, 180, -60, 83]`` for LCM-10).
        globe_views: One :class:`GlobeView` per panel.
        background: ``"black"``, ``"white"``, or ``"transparent"``.
        globe_size_px: Width of each panel in pixels.
        globe_gap_px: Gap between adjacent panels in pixels; outer margins
            are half this value.
        dpi: Output resolution in dots per inch.
        bg_rgb: Optional (H, W, 3) uint8 RGB background imagery.  ``None``
            → use Cartopy's built-in Natural Earth stock image instead.
        bg_extent: ``[left, right, bottom, top]`` for ``bg_rgb``.  Ignored
            when ``bg_rgb`` is ``None``.
        coastlines: When ``True``, draw coastline outlines.
        country_borders: When ``True``, overlay Natural Earth country borders.
        border_color: Shared edge colour for coastlines and country borders.
        border_width: Shared line width for coastlines and country borders.
        aspect_ratio: Panel width / panel height.  ``1.0`` = square;
            ``1.78`` ≈ 16:9; ``1.33`` ≈ 4:3.

    Returns:
        Configured :class:`matplotlib.figure.Figure`.
    """
    n = len(globe_views)
    panel_h_px = round(globe_size_px / aspect_ratio)

    # ---- Figure dimensions ------------------------------------------------
    # Total width  = N × (panel_w + gap)  ;  outer margin = gap/2 on each side
    # Total height =      panel_h + gap   ;  outer margin = gap/2 top and bottom
    fig_w_px = n * (globe_size_px + globe_gap_px)
    fig_h_px = panel_h_px + globe_gap_px
    fig_w_in = fig_w_px / dpi
    fig_h_in = fig_h_px / dpi

    # ---- Subplot layout fractions -----------------------------------------
    # left/right/bottom/top anchor the panel array within the figure canvas.
    # wspace = inter-panel gap / panel width  (matplotlib convention).
    half_gap    = globe_gap_px / 2
    left_frac   = half_gap / fig_w_px
    right_frac  = 1.0 - half_gap / fig_w_px
    bottom_frac = half_gap / fig_h_px
    top_frac    = 1.0 - half_gap / fig_h_px
    wspace      = globe_gap_px / globe_size_px

    # ---- Background colour ------------------------------------------------
    if background == "transparent":
        bg_rgba = (0.0, 0.0, 0.0, 0.0)
    elif background == "white":
        bg_rgba = (1.0, 1.0, 1.0, 1.0)
    else:  # "black" default
        bg_rgba = (0.0, 0.0, 0.0, 1.0)

    fig = plt.figure(figsize=(fig_w_in, fig_h_in), facecolor=bg_rgba)

    for i, view in enumerate(globe_views):
        proj = ccrs.Orthographic(central_longitude=view.lon, central_latitude=view.lat)
        ax = fig.add_subplot(1, n, i + 1, projection=proj)
        ax.set_facecolor(bg_rgba)

        # --- Background layer (zorder 0) -----------------------------------
        if bg_rgb is not None:
            ax.imshow(
                bg_rgb,
                origin="upper",
                extent=bg_extent,
                transform=ccrs.PlateCarree(),
                interpolation="bilinear",
                zorder=0,
            )
        else:
            # Cartopy's built-in Natural Earth shaded-relief image.
            ax.stock_img()

        # --- LCM-10 overlay (zorder 1) -------------------------------------
        # No-data pixels (alpha=0) are transparent, letting the background
        # show through in areas outside the LCM-10 coverage (60°S – 83°N).
        ax.imshow(
            rgba,
            origin="upper",
            extent=lcm_extent,
            transform=ccrs.PlateCarree(),
            interpolation="nearest",
            zorder=1,
        )

        # --- Coastlines / country borders (zorder 2) -----------------------
        if coastlines:
            ax.add_feature(
                cfeature.COASTLINE,
                linewidth=border_width,
                edgecolor=border_color,
                zorder=2,
            )
        if country_borders:
            ax.add_feature(
                cfeature.BORDERS,
                linewidth=border_width,
                edgecolor=border_color,
                facecolor="none",
                zorder=2,
            )

        # --- View extent ---------------------------------------------------
        if view.zoom is not None:
            # Rectangular screen crop: compute the half-extents in projection
            # metres using standard WebMercator tile math, cos(lat)-adjusted.
            # set_extent with crs=proj uses projection-native metre units.
            # half_h < half_w when aspect_ratio > 1 (wider than tall).
            mpp    = zoom_to_mpp(view.zoom, view.lat)
            half_w = (globe_size_px / 2) * mpp
            half_h = (panel_h_px    / 2) * mpp
            ax.set_extent([-half_w, half_w, -half_h, half_h], crs=proj)
        else:
            # Full circular globe (Cartopy default circular boundary).
            ax.set_global()

    fig.subplots_adjust(
        left=left_frac, right=right_frac,
        bottom=bottom_frac, top=top_frac,
        wspace=wspace, hspace=0,
    )
    return fig


# ---------------------------------------------------------------------------
# Config I/O
# ---------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    """Read a TOML config file and return the parsed dictionary.

    Args:
        path: Path to a ``.toml`` file with an optional ``[global]`` section
            and one or more ``[[render]]`` entries.

    Returns:
        Dictionary of parsed TOML content.
    """
    with open(path, "rb") as f:
        return tomllib.load(f)


def _parse_globe_views(entry: dict) -> list[GlobeView]:
    """Build a list of :class:`GlobeView` objects from a ``[[render]]`` entry.

    Accepts either:

    - ``maplibre_url``: one view, zoom/lat/lon parsed from the URL hash.
    - ``globe_centers``: list of ``[lon, lat]`` pairs, no zoom.

    Args:
        entry: A single ``[[render]]`` dictionary from the TOML config.

    Returns:
        List of :class:`GlobeView` objects.

    Raises:
        KeyError: If neither ``maplibre_url`` nor ``globe_centers`` is present.
    """
    if "maplibre_url" in entry:
        return [globe_view_from_maplibre_url(entry["maplibre_url"])]
    return [GlobeView(lon=float(c[0]), lat=float(c[1])) for c in entry["globe_centers"]]


def run_all_renders(config: dict) -> None:
    """Execute every ``[[render]]`` entry in a loaded TOML config.

    COG data is loaded once and reused across all renders to avoid redundant
    network round-trips.

    Args:
        config: Parsed TOML dictionary (from :func:`load_config`).
    """
    g = config.get("global", {})

    cog_url    = g.get("cog_url",              COG_URL)
    downsample = g.get("downsample_factor",    DOWNSAMPLE_FACTOR)
    bg_cog     = g.get("bg_cog_url",           BG_COG_URL)
    bg_ds      = g.get("bg_downsample_factor", BG_DOWNSAMPLE_FACTOR)

    rgba, lcm_extent = load_data(cog_url, downsample)
    bg_rgb: np.ndarray | None = None
    bg_extent: list[float] | None = None
    if bg_cog:
        bg_rgb, bg_extent = load_background(bg_cog, bg_ds)

    for entry in config.get("render", []):
        globe_views = _parse_globe_views(entry)
        name   = entry.get("name", "render")
        output = Path(entry.get("output", f"images/{name}.png"))
        output.parent.mkdir(parents=True, exist_ok=True)

        # Per-render overrides fall back to [global] then module constants.
        background = entry.get("background",      g.get("background",      BACKGROUND))
        globe_size = entry.get("globe_size_px",   g.get("globe_size_px",   GLOBE_SIZE_PX))
        globe_gap  = entry.get("globe_gap_px",    g.get("globe_gap_px",    GLOBE_GAP_PX))
        dpi        = entry.get("dpi",             g.get("dpi",             DPI))
        clines      = entry.get("coastlines",      g.get("coastlines",      COASTLINES))
        cborders    = entry.get("country_borders", g.get("country_borders", COUNTRY_BORDERS))
        bcol        = entry.get("border_color",    g.get("border_color",    BORDER_COLOR))
        bwidth      = entry.get("border_width",    g.get("border_width",    BORDER_WIDTH))
        asp         = entry.get("aspect_ratio",    g.get("aspect_ratio",    1.0))

        n = len(globe_views)
        print(f"\nRendering '{name}' ({n} globe(s)) → {output} ...")
        fig = build_figure(
            rgba=rgba,
            lcm_extent=lcm_extent,
            globe_views=globe_views,
            background=background,
            globe_size_px=globe_size,
            globe_gap_px=globe_gap,
            dpi=dpi,
            bg_rgb=bg_rgb,
            bg_extent=bg_extent,
            coastlines=clines,
            country_borders=cborders,
            border_color=bcol,
            border_width=bwidth,
            aspect_ratio=asp,
        )
        transparent = background == "transparent"
        fig.savefig(output, dpi=dpi, transparent=transparent, facecolor=fig.get_facecolor())
        plt.close(fig)
        print(f"  Saved → {output}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render orthographic globe(s) of the LCM-10 land cover map.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        help=(
            "TOML config file; each [[render]] entry produces one output PNG.  "
            "Without this flag the module-level constants are used."
        ),
    )
    args = parser.parse_args()

    if args.config:
        config = load_config(args.config)
        run_all_renders(config)
        return

    # Fallback: use hardcoded module-level constants.
    rgba, lcm_extent = load_data(COG_URL, DOWNSAMPLE_FACTOR)
    bg_rgb: np.ndarray | None = None
    bg_extent: list[float] | None = None
    if BG_COG_URL:
        bg_rgb, bg_extent = load_background(BG_COG_URL, BG_DOWNSAMPLE_FACTOR)

    n = len(GLOBE_VIEWS)
    bg_label = BG_COG_URL or "stock_img"
    print(f"Building {n}-globe figure (background={BACKGROUND!r}, base={bg_label}) ...")
    fig = build_figure(
        rgba=rgba,
        lcm_extent=lcm_extent,
        globe_views=GLOBE_VIEWS,
        background=BACKGROUND,
        globe_size_px=GLOBE_SIZE_PX,
        globe_gap_px=GLOBE_GAP_PX,
        dpi=DPI,
        bg_rgb=bg_rgb,
        bg_extent=bg_extent,
        coastlines=COASTLINES,
        country_borders=COUNTRY_BORDERS,
        border_color=BORDER_COLOR,
        border_width=BORDER_WIDTH,
    )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    transparent = BACKGROUND == "transparent"
    fig.savefig(OUTPUT_PATH, dpi=DPI, transparent=transparent, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Saved → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
