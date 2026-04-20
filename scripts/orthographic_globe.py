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
import matplotlib.path as mpath
import matplotlib.pyplot as plt
import numpy as np
import rasterio
import rasterio.windows as rwin
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

# Downsample factor relative to native resolution (36 000 × 14 275 px).
# None → auto-select the optimal pre-built COG overview for the current
# globe_size_px and visible geographic extent.  Set an explicit integer to
# override (e.g. 8 → ~4 500 × 1 784 px).
DOWNSAMPLE_FACTOR: int | None = None

# Optional background imagery COG (3-band RGB uint8, EPSG:4326).
# None → use Cartopy's built-in Natural Earth stock image (ax.stock_img()).
BG_COG_URL: str | None = (
    "https://vito-lcf-shapefiles-waw4-1.s3.waw4-1.cloudferro.com/"
    "world_topo_bathy_200407_WGS84.tif"
)
# Downsample factor for the background COG.  None → auto-select.
BG_DOWNSAMPLE_FACTOR: int | None = None

# Oversampling quality factor used when selecting a COG overview for
# full-globe renders.  1.0 = 1 source pixel per output pixel (minimum);
# 2.0 = 2 source pixels per output pixel (sharper; 4× data but still
#        served from pre-built overviews — no extra network cost per tile).
# Zoomed renders always use windowed native-resolution reads instead.
QUALITY_SCALE: float = 2.0

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


def _visible_width_deg_for_render(
    views: list[GlobeView], globe_size_px: int
) -> float:
    """Return the most-demanding visible geographic width across all views.

    For views without a zoom (full globe), visible width = 180°.
    For zoomed views the visible width is computed from zoom level and latitude
    using standard WebMercator tile math.

    Returns the *minimum* of all views — the most demanding (finest-resolution)
    case drives the COG overview selection.

    Args:
        views: List of GlobeView objects for this render.
        globe_size_px: Panel width in pixels.

    Returns:
        Visible width in degrees (> 0, ≤ 180).
    """
    widths: list[float] = []
    for v in views:
        if v.zoom is None:
            widths.append(180.0)
        else:
            widths.append(globe_size_px * zoom_to_mpp(v.zoom, v.lat) / 111_320.0)
    return min(widths)


def _optimal_factor(
    src: rasterio.DatasetReader,
    globe_size_px: int,
    visible_width_deg: float,
    quality_scale: float = 1.0,
) -> int:
    """Select the coarsest COG overview that satisfies the quality threshold.

    The effective ideal factor requires ``quality_scale`` source pixels per
    output pixel::

        effective_ideal = native_width × visible_width_deg
                          / (360 × globe_size_px × quality_scale)

    With ``quality_scale = 1.0`` the function selects the coarsest overview
    that gives ≥ 1 source pixel per output pixel.  With ``quality_scale = 2.0``
    it requires ≥ 2 source pixels per output pixel (sharper, costs 4× data
    but served from pre-built overviews).

    Returns the *largest* available pre-built overview factor ≤ the effective
    ideal — the coarsest valid overview.  Falls back to 1 (native resolution)
    if every available overview is coarser than needed.

    Args:
        src: Open rasterio dataset.
        globe_size_px: Output panel width in pixels.
        visible_width_deg: Geographic width visible on screen in degrees.
        quality_scale: Minimum source-pixels-per-output-pixel ratio.
            1.0 = bare minimum; 2.0 = recommended for print.

    Returns:
        Integer decimation factor.
    """
    ideal = src.width * visible_width_deg / (360.0 * globe_size_px * quality_scale)
    overviews = src.overviews(1)
    candidates = [f for f in overviews if f <= ideal]
    factor = max(candidates) if candidates else 1
    print(
        f"  auto factor {factor} (ideal {ideal:.1f}, qs={quality_scale:.1f})"
        f" — {globe_size_px}px panel, {visible_width_deg:.1f}° visible"
    )
    return factor


def _bbox_for_view(
    view: GlobeView,
    globe_size_px: int,
    aspect_ratio: float = 1.0,
    buffer: float = 0.2,
) -> tuple[float, float, float, float] | None:
    """Return the geographic bounding box (lon_min, lat_min, lon_max, lat_max)
    visible for a zoomed :class:`GlobeView`, with an optional padding buffer.

    Returns ``None`` for full-globe views (``view.zoom is None``), which
    should always use full-extent overview reads instead.

    The visible half-widths in degrees are derived from the WebMercator tile
    math already used by ``zoom_to_mpp``.  A ``buffer`` fraction is added on
    all sides so Cartopy can anti-alias edges correctly.

    Args:
        view: Globe camera position.  ``view.zoom`` must not be ``None``.
        globe_size_px: Panel width in pixels.
        aspect_ratio: Panel width / panel height (1.0 = square).
        buffer: Fractional padding added on each side (default 20 %).

    Returns:
        ``(lon_min, lat_min, lon_max, lat_max)`` in degrees, clamped to
        ±180 /  ±90, or ``None`` for full-globe views.
    """
    if view.zoom is None:
        return None
    panel_h_px = globe_size_px / aspect_ratio
    mpp = zoom_to_mpp(view.zoom, view.lat)
    half_w_m = (globe_size_px / 2) * mpp * (1 + buffer)
    half_h_m = (panel_h_px   / 2) * mpp * (1 + buffer)
    # Convert metres → degrees (approximate; exact enough for window selection).
    cos_lat = math.cos(math.radians(view.lat))
    half_lon = half_w_m / (111_320.0 * cos_lat) if cos_lat > 1e-9 else 180.0
    half_lat = half_h_m / 111_320.0
    return (
        max(-180.0, view.lon - half_lon),
        max( -90.0, view.lat - half_lat),
        min( 180.0, view.lon + half_lon),
        min(  90.0, view.lat + half_lat),
    )


def _render_bbox(
    views: list[GlobeView],
    globe_size_px: int,
    aspect_ratio: float = 1.0,
) -> tuple[float, float, float, float] | None:
    """Return the union bounding box across all zoomed views in a render.

    Returns ``None`` if any view is a full-globe view (``zoom is None``), so
    the caller falls back to the full-extent overview path.

    Args:
        views: All :class:`GlobeView` objects for one render entry.
        globe_size_px: Panel width in pixels.
        aspect_ratio: Panel width / height ratio passed to :func:`_bbox_for_view`.

    Returns:
        Union ``(lon_min, lat_min, lon_max, lat_max)`` or ``None``.
    """
    boxes = [_bbox_for_view(v, globe_size_px, aspect_ratio) for v in views]
    if any(b is None for b in boxes):
        return None
    lon_min = min(b[0] for b in boxes)   # type: ignore[index]
    lat_min = min(b[1] for b in boxes)   # type: ignore[index]
    lon_max = max(b[2] for b in boxes)   # type: ignore[index]
    lat_max = max(b[3] for b in boxes)   # type: ignore[index]
    return lon_min, lat_min, lon_max, lat_max


def _read_window_native(
    src: rasterio.DatasetReader,
    bbox: tuple[float, float, float, float],
    bands: list[int] | None = None,
    out_shape: tuple[int, ...] | None = None,
    resampling: Resampling = Resampling.nearest,
) -> tuple[np.ndarray, list[float]]:
    """Read an exact geographic window from a COG, optionally resampled.

    Uses HTTP range requests so only the COG tiles that overlap ``bbox`` are
    fetched.  The window is snapped to the pixel grid, so the returned extent
    may be slightly larger than ``bbox``.

    Args:
        src: Open rasterio dataset.
        bbox: ``(lon_min, lat_min, lon_max, lat_max)`` in the dataset's CRS
            (assumed EPSG:4326 degrees).
        bands: 1-based list of band indices to read.  ``None`` = all bands.
        out_shape: If provided, rasterio resamples the window to this shape
            ``(bands, H, W)`` during the read, avoiding a large intermediate
            array.  Pair with ``resampling`` to control the algorithm.
        resampling: Resampling algorithm used when ``out_shape`` is set.
            Use ``Resampling.mode`` for categorical data and
            ``Resampling.bilinear`` for continuous imagery.

    Returns:
        Tuple of (data array ``(bands, H, W)``), extent ``[left, right,
        bottom, top]``).
    """
    lon_min, lat_min, lon_max, lat_max = bbox
    # Clamp to dataset bounds to avoid reading outside the file.
    b = src.bounds
    lon_min = max(lon_min, b.left)
    lat_min = max(lat_min, b.bottom)
    lon_max = min(lon_max, b.right)
    lat_max = min(lat_max, b.top)
    if lon_min >= lon_max or lat_min >= lat_max:
        raise ValueError(
            f"bbox {bbox} does not intersect dataset bounds {tuple(b)}"
        )
    window = rwin.from_bounds(lon_min, lat_min, lon_max, lat_max, src.transform)
    # Round outward to full pixels so the extent is exact.
    window = window.round_offsets().round_lengths()
    kwargs: dict = {}
    if bands is not None:
        kwargs["indexes"] = bands
    if out_shape is not None:
        kwargs["out_shape"] = out_shape
        kwargs["resampling"] = resampling
    data = src.read(window=window, **kwargs)
    left, bottom, right, top = rwin.bounds(window, src.transform)
    extent = [left, right, bottom, top]
    print(
        f"  windowed read {data.shape[-1]} \u00d7 {data.shape[-2]} px"
        f" (resampled from window)"
        f", bbox {lon_min:.1f}..{lon_max:.1f}\u00b0lon"
        f" {lat_min:.1f}..{lat_max:.1f}\u00b0lat"
    )
    return data, extent


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


def load_data(
    cog_url: str,
    globe_size_px: int,
    visible_width_deg: float,
    downsample: int | None = None,
    quality_scale: float = 1.0,
    bbox: tuple[float, float, float, float] | None = None,
) -> tuple[np.ndarray, list[float]]:
    """Open the LCM-10 COG and return an RGBA (H, W, 4) array and its extent.

    Uses ``Resampling.mode`` as fallback (majority vote — correct for
    categorical data).

    When ``bbox`` is provided the dataset is read as a geographic window at
    native resolution via HTTP range requests (zoomed renders).  When
    ``bbox`` is ``None`` a full-extent pre-built COG overview is selected
    by ``_optimal_factor`` (full-globe renders).

    Args:
        cog_url: HTTPS URL or local path to the Cloud-Optimized GeoTIFF.
        globe_size_px: Output panel width in pixels; used to auto-select the
            optimal COG overview when ``downsample`` is ``None``.
        visible_width_deg: Geographic width visible on the panel in degrees
            (180 for a full globe; smaller for a zoomed view).
        downsample: Integer decimation factor.  ``None`` = auto-select.
            Ignored when ``bbox`` is set.
        quality_scale: Minimum source-pixels-per-output-pixel ratio passed
            to ``_optimal_factor``.  Ignored when ``bbox`` is set.
        bbox: ``(lon_min, lat_min, lon_max, lat_max)`` in degrees.  When set,
            a windowed native-resolution read is performed instead of a
            full-extent overview read.

    Returns:
        Tuple of (RGBA array, extent) where extent is
        ``[left, right, bottom, top]`` in degrees.
    """
    print(f"Opening LCM-10 COG: {cog_url}")
    with rasterio.open(cog_url) as src:
        print(f"  native size : {src.width} × {src.height}")
        print(f"  overviews   : {src.overviews(1)}")
        if bbox is not None:
            lon_span = max(bbox[2] - bbox[0], 0.001)
            lat_span = max(bbox[3] - bbox[1], 0.001)
            tgt_w = max(256, round(globe_size_px * quality_scale))
            tgt_h = max(256, round(tgt_w * lat_span / lon_span))
            out_shape = (src.count, tgt_h, tgt_w)
            print(f"  target shape: {tgt_w} × {tgt_h} (quality_scale={quality_scale})")
            data, extent = _read_window_native(
                src, bbox, out_shape=out_shape, resampling=Resampling.mode
            )
        else:
            b = src.bounds
            extent = [b.left, b.right, b.bottom, b.top]
            print(f"  extent      : {extent}")
            if downsample is None:
                downsample = _optimal_factor(
                    src, globe_size_px, visible_width_deg, quality_scale
                )
            data = _read_overview(src, downsample, Resampling.mode)

    band       = data[0]
    alpha_band = data[1] if data.shape[0] > 1 else np.full_like(band, 255)

    print("  applying colormap ...")
    rgba = apply_colormap(band, alpha_band, COLORMAP_HEX)
    print(f"  done — RGBA shape {rgba.shape}")
    return rgba, extent


def load_background(
    cog_url: str,
    globe_size_px: int,
    visible_width_deg: float,
    downsample: int | None = None,
    quality_scale: float = 1.0,
    bbox: tuple[float, float, float, float] | None = None,
) -> tuple[np.ndarray, list[float]]:
    """Open a background imagery COG and return an (H, W, 3) RGB array and extent.

    Reads only the first three bands (R, G, B).  Uses ``Resampling.bilinear``
    as fallback, which is appropriate for continuous imagery.

    When ``bbox`` is provided the dataset is read as a geographic window at
    native resolution.  Otherwise a full-extent overview is selected via
    ``_optimal_factor``.

    Args:
        cog_url: HTTPS URL or local path to a 3-band uint8 EPSG:4326 COG.
        globe_size_px: Output panel width in pixels; used to auto-select the
            optimal COG overview when ``downsample`` is ``None``.
        visible_width_deg: Geographic width visible on the panel in degrees
            (180 for a full globe; smaller for a zoomed view).
        downsample: Integer decimation factor.  ``None`` = auto-select.
            Ignored when ``bbox`` is set.
        quality_scale: Passed to ``_optimal_factor``.  Ignored when ``bbox``
            is set.
        bbox: ``(lon_min, lat_min, lon_max, lat_max)`` in degrees for a
            windowed native-resolution read.

    Returns:
        Tuple of (RGB array, extent) where extent is
        ``[left, right, bottom, top]`` in degrees, read from the COG metadata.
    """
    print(f"Opening background COG: {cog_url}")
    with rasterio.open(cog_url) as src:
        print(f"  native size : {src.width} × {src.height}")
        print(f"  overviews   : {src.overviews(1)}")
        if bbox is not None:
            lon_span = max(bbox[2] - bbox[0], 0.001)
            lat_span = max(bbox[3] - bbox[1], 0.001)
            tgt_w = max(256, round(globe_size_px * quality_scale))
            tgt_h = max(256, round(tgt_w * lat_span / lon_span))
            out_shape = (3, tgt_h, tgt_w)
            print(f"  target shape: {tgt_w} × {tgt_h} (quality_scale={quality_scale})")
            data, extent = _read_window_native(
                src, bbox, bands=[1, 2, 3], out_shape=out_shape, resampling=Resampling.bilinear
            )
        else:
            b = src.bounds
            extent = [b.left, b.right, b.bottom, b.top]
            print(f"  extent      : {extent}")
            if downsample is None:
                downsample = _optimal_factor(
                    src, globe_size_px, visible_width_deg, quality_scale
                )
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
            interpolation="antialiased",
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
            # half_h < half_w when aspect_ratio > 1 (wider than tall).
            mpp    = zoom_to_mpp(view.zoom, view.lat)
            half_w = (globe_size_px / 2) * mpp
            half_h = (panel_h_px    / 2) * mpp
            # Cartopy forces aspect='equal' on Orthographic GeoAxes, which
            # makes the globe a circle that fills the axes height, leaving
            # transparent sides.  Override with 'auto' so the xlim/ylim
            # below map the projection metres directly to the panel pixels.
            ax.set_aspect('auto')
            # Clip to the full axes rectangle (screen space) so the circular
            # globe horizon is not visible inside the viewport.
            ax.set_boundary(mpath.Path.unit_rectangle(), transform=ax.transAxes)
            # Set viewport in projection metres directly — set_extent() has
            # known issues with Orthographic when crs=proj is passed.
            ax.set_xlim(-half_w, half_w)
            ax.set_ylim(-half_h, half_h)
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


def run_all_renders(config: dict, names: set[str] | None = None) -> None:
    """Execute every ``[[render]]`` entry in a loaded TOML config.

    COG data is loaded per-render at the optimal resolution for that render's
    panel size and visible extent.  Results are cached by call arguments so
    consecutive renders with the same parameters (e.g. multiple full-globe
    panels at the same size) share a single network read.

    Args:
        config: Parsed TOML dictionary (from :func:`load_config`).
        names: Optional set of render names to execute.  ``None`` runs all.
    """
    g = config.get("global", {})

    cog_url = g.get("cog_url",    COG_URL)
    bg_cog  = g.get("bg_cog_url", BG_COG_URL)
    # Explicit factors from [global]; None = auto-calculate per render.
    g_ds    = g.get("downsample_factor",    DOWNSAMPLE_FACTOR)
    g_bg_ds = g.get("bg_downsample_factor", BG_DOWNSAMPLE_FACTOR)
    g_qs    = g.get("quality_scale",        QUALITY_SCALE)

    # Cache loaded arrays by (fn, url, globe_size_px, visible_width_deg, ds, qs, bbox)
    # so renders with identical parameters skip the COG download.
    _cache: dict[tuple, tuple] = {}

    def _load(fn, url, globe_size_px, vwd, ds, qs, bbox):
        key = (fn, url, globe_size_px, vwd, ds, qs, bbox)
        if key not in _cache:
            _cache[key] = fn(url, globe_size_px, vwd, ds, qs, bbox)
        return _cache[key]

    for entry in config.get("render", []):
        name   = entry.get("name", "render")
        if names is not None and name not in names:
            continue
        globe_views = _parse_globe_views(entry)
        output = Path(entry.get("output", f"images/{name}.png"))
        output.parent.mkdir(parents=True, exist_ok=True)

        # Per-render overrides fall back to [global] then module constants.
        background = entry.get("background",      g.get("background",      BACKGROUND))
        globe_size = entry.get("globe_size_px",   g.get("globe_size_px",   GLOBE_SIZE_PX))
        globe_gap  = entry.get("globe_gap_px",    g.get("globe_gap_px",    GLOBE_GAP_PX))
        dpi        = entry.get("dpi",             g.get("dpi",             DPI))
        clines     = entry.get("coastlines",      g.get("coastlines",      COASTLINES))
        cborders   = entry.get("country_borders", g.get("country_borders", COUNTRY_BORDERS))
        bcol       = entry.get("border_color",    g.get("border_color",    BORDER_COLOR))
        bwidth     = entry.get("border_width",    g.get("border_width",    BORDER_WIDTH))
        asp        = entry.get("aspect_ratio",    g.get("aspect_ratio",    1.0))
        # Explicit per-render downsample override, or fall back to global, or auto.
        ds    = entry.get("downsample_factor",    g_ds)
        bg_ds = entry.get("bg_downsample_factor", g_bg_ds)
        qs    = entry.get("quality_scale",        g_qs)

        # Compute the most-demanding visible geographic width across all views.
        vwd  = _visible_width_deg_for_render(globe_views, globe_size)
        # For zoomed renders use a windowed native-resolution read instead of
        # a full-extent overview; None means fall back to the overview path.
        bbox = _render_bbox(globe_views, globe_size, asp)

        n = len(globe_views)
        print(f"\nRendering '{name}' ({n} globe(s)) → {output} ...")
        rgba, lcm_extent = _load(load_data, cog_url, globe_size, vwd, ds, qs, bbox)

        bg_rgb: np.ndarray | None = None
        bg_extent: list[float] | None = None
        if bg_cog:
            bg_rgb, bg_extent = _load(load_background, bg_cog, globe_size, vwd, bg_ds, qs, bbox)

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
    parser.add_argument(
        "--name",
        nargs="+",
        metavar="NAME",
        help="Only render entries whose 'name' field matches one of these values.",
    )
    args = parser.parse_args()

    if args.config:
        config = load_config(args.config)
        name_filter = set(args.name) if args.name else None
        run_all_renders(config, names=name_filter)
        return

    # Fallback: use hardcoded module-level constants.
    vwd  = _visible_width_deg_for_render(GLOBE_VIEWS, GLOBE_SIZE_PX)
    bbox = _render_bbox(GLOBE_VIEWS, GLOBE_SIZE_PX)
    rgba, lcm_extent = load_data(
        COG_URL, GLOBE_SIZE_PX, vwd, DOWNSAMPLE_FACTOR, QUALITY_SCALE, bbox
    )
    bg_rgb: np.ndarray | None = None
    bg_extent: list[float] | None = None
    if BG_COG_URL:
        bg_rgb, bg_extent = load_background(
            BG_COG_URL, GLOBE_SIZE_PX, vwd, BG_DOWNSAMPLE_FACTOR, QUALITY_SCALE, bbox
        )

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
