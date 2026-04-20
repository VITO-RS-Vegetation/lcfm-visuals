"""Unit tests for orthographic_globe helper functions.

All tests are pure-Python (no network access, no COG downloads).

Integration tests that download COG data are marked with
``@pytest.mark.integration``.  They are excluded from the default run; opt in
with::

    pytest -m integration
"""
from __future__ import annotations

import math
import tomllib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orthographic_globe import (
    GlobeView,
    _bbox_for_view,
    _optimal_factor,
    _parse_globe_views,
    _render_bbox,
    _visible_width_deg_for_render,
    globe_view_from_maplibre_url,
    parse_maplibre_hash,
    zoom_to_mpp,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

EXAMPLE_URL = (
    "https://raw.githack.com/VITO-RS-Vegetation/lcfm-visuals/"
    "5ed1c6a75b7cbec0a8878c8f0c13e25d8d0655ed/html/globe_maplibre.html"
    "#3.47/39.33/3.76"
)

CONFIG_PATH = Path(__file__).parent.parent / "configs" / "globes.toml"


# ---------------------------------------------------------------------------
# parse_maplibre_hash
# ---------------------------------------------------------------------------

def test_parse_maplibre_hash_full_url():
    zoom, lat, lon = parse_maplibre_hash(EXAMPLE_URL)
    assert zoom == pytest.approx(3.47)
    assert lat  == pytest.approx(39.33)
    assert lon  == pytest.approx(3.76)


def test_parse_maplibre_hash_bare_with_prefix():
    zoom, lat, lon = parse_maplibre_hash("#3.47/39.33/3.76")
    assert zoom == pytest.approx(3.47)
    assert lat  == pytest.approx(39.33)
    assert lon  == pytest.approx(3.76)


def test_parse_maplibre_hash_bare_no_prefix():
    zoom, lat, lon = parse_maplibre_hash("3.47/39.33/3.76")
    assert zoom == pytest.approx(3.47)
    assert lat  == pytest.approx(39.33)
    assert lon  == pytest.approx(3.76)


def test_parse_maplibre_hash_with_bearing_pitch():
    """Bearing and pitch (extra parts) are silently ignored."""
    zoom, lat, lon = parse_maplibre_hash("#3.47/39.33/3.76/45.0/30.0")
    assert zoom == pytest.approx(3.47)
    assert lat  == pytest.approx(39.33)
    assert lon  == pytest.approx(3.76)


def test_parse_maplibre_hash_too_few_parts():
    with pytest.raises(ValueError, match="zoom/lat/lng"):
        parse_maplibre_hash("#3.47/39.33")  # missing lng


# ---------------------------------------------------------------------------
# zoom_to_mpp
# ---------------------------------------------------------------------------

def test_zoom_to_mpp_equator_zoom0():
    """At zoom=0, lat=0 the whole world spans 512 px → mpp = circumference/512."""
    mpp = zoom_to_mpp(0.0, 0.0)
    assert mpp == pytest.approx(40_075_016.68 / 512.0, rel=1e-6)


def test_zoom_to_mpp_matches_formula():
    zoom, lat = 3.47, 39.33
    expected = (40_075_016.68 / (512.0 * (2.0 ** zoom))) * math.cos(math.radians(lat))
    assert zoom_to_mpp(zoom, lat) == pytest.approx(expected, rel=1e-9)


def test_zoom_to_mpp_decreases_with_zoom():
    """Higher zoom → smaller metres-per-pixel (more zoomed in)."""
    assert zoom_to_mpp(5.0, 0.0) < zoom_to_mpp(3.0, 0.0)


def test_zoom_to_mpp_decreases_with_latitude():
    """Higher latitude → cos correction reduces mpp."""
    assert zoom_to_mpp(3.0, 60.0) < zoom_to_mpp(3.0, 0.0)


# ---------------------------------------------------------------------------
# globe_view_from_maplibre_url
# ---------------------------------------------------------------------------

def test_globe_view_from_maplibre_url_fields():
    view = globe_view_from_maplibre_url(EXAMPLE_URL)
    assert isinstance(view, GlobeView)
    assert view.lon  == pytest.approx(3.76)
    assert view.lat  == pytest.approx(39.33)
    assert view.zoom == pytest.approx(3.47)


def test_globe_view_lon_lat_swap():
    """MapLibre hash is zoom/lat/lng; GlobeView must store lon=lng, lat=lat."""
    view = globe_view_from_maplibre_url("#1.0/10.0/20.0")
    assert view.lat == pytest.approx(10.0)
    assert view.lon == pytest.approx(20.0)


def test_globe_view_zoom_is_set():
    """GlobeView created from a MapLibre URL always carries a zoom."""
    view = globe_view_from_maplibre_url(EXAMPLE_URL)
    assert view.zoom is not None


# ---------------------------------------------------------------------------
# GlobeView dataclass
# ---------------------------------------------------------------------------

def test_globe_view_default_zoom_is_none():
    view = GlobeView(lon=10.0, lat=20.0)
    assert view.zoom is None


def test_globe_view_equality():
    assert GlobeView(lon=-90.0, lat=15.0) == GlobeView(lon=-90.0, lat=15.0)
    assert GlobeView(lon=-90.0, lat=15.0) != GlobeView(lon=60.0, lat=25.0)


# ---------------------------------------------------------------------------
# TOML config
# ---------------------------------------------------------------------------

def test_config_has_four_renders():
    with open(CONFIG_PATH, "rb") as fh:
        config = tomllib.load(fh)
    assert len(config.get("render", [])) == 4


def test_config_has_maplibre_entry():
    with open(CONFIG_PATH, "rb") as fh:
        config = tomllib.load(fh)
    maplibre = [r for r in config["render"] if "maplibre_url" in r]
    assert len(maplibre) == 1


def test_config_render_names():
    with open(CONFIG_PATH, "rb") as fh:
        config = tomllib.load(fh)
    names = {r["name"] for r in config["render"]}
    assert names == {"1_globe", "2_globes", "3_globes", "maplibre_link"}


def test_config_global_section_present():
    with open(CONFIG_PATH, "rb") as fh:
        config = tomllib.load(fh)
    g = config.get("global", {})
    assert "globe_size_px" in g
    assert "globe_gap_px" in g
    assert "dpi" in g


# ---------------------------------------------------------------------------
# _parse_globe_views
# ---------------------------------------------------------------------------

def test_parse_globe_views_from_centers():
    entry = {"globe_centers": [[-90.0, 15.0], [60.0, 25.0]]}
    views = _parse_globe_views(entry)
    assert len(views) == 2
    assert views[0] == GlobeView(lon=-90.0, lat=15.0)
    assert views[1] == GlobeView(lon=60.0,  lat=25.0)
    assert all(v.zoom is None for v in views)


def test_parse_globe_views_from_maplibre_url():
    entry = {"maplibre_url": EXAMPLE_URL}
    views = _parse_globe_views(entry)
    assert len(views) == 1
    assert views[0].lon  == pytest.approx(3.76)
    assert views[0].zoom == pytest.approx(3.47)


def test_parse_globe_views_1_globe_config():
    with open(CONFIG_PATH, "rb") as fh:
        config = tomllib.load(fh)
    entry = next(r for r in config["render"] if r.get("name") == "1_globe")
    views = _parse_globe_views(entry)
    assert len(views) == 1
    assert views[0].zoom is None


def test_parse_globe_views_2_globes_config():
    with open(CONFIG_PATH, "rb") as fh:
        config = tomllib.load(fh)
    entry = next(r for r in config["render"] if r.get("name") == "2_globes")
    views = _parse_globe_views(entry)
    assert len(views) == 2
    assert all(v.zoom is None for v in views)


def test_parse_globe_views_3_globes_config():
    with open(CONFIG_PATH, "rb") as fh:
        config = tomllib.load(fh)
    entry = next(r for r in config["render"] if r.get("name") == "3_globes")
    views = _parse_globe_views(entry)
    assert len(views) == 3


def test_parse_globe_views_maplibre_config():
    with open(CONFIG_PATH, "rb") as fh:
        config = tomllib.load(fh)
    entry = next(r for r in config["render"] if "maplibre_url" in r)
    views = _parse_globe_views(entry)
    assert len(views) == 1
    assert views[0].zoom is not None


# ---------------------------------------------------------------------------
# _optimal_factor
# ---------------------------------------------------------------------------

def _mock_src(width: int, overviews: list[int]) -> MagicMock:
    src = MagicMock()
    src.width = width
    src.overviews.return_value = overviews
    return src


def test_optimal_factor_full_globe_lcm10():
    # LCM-10: 36 000 px wide, overviews [2,4,8,16,32,64,128], panel 2100 px
    # ideal = 36000 * 180 / (360 * 2100) ≈ 8.57 → largest ov. ≤ 8.57 → 8
    src = _mock_src(36_000, [2, 4, 8, 16, 32, 64, 128])
    assert _optimal_factor(src, 2100, 180.0) == 8


def test_optimal_factor_full_globe_bg_cog():
    # BG COG: 21 600 px wide, overviews [2,4,8,16,32,64], panel 2100 px
    # ideal = 21600 * 180 / (360 * 2100) ≈ 5.14 → largest ov. ≤ 5.14 → 4
    src = _mock_src(21_600, [2, 4, 8, 16, 32, 64])
    assert _optimal_factor(src, 2100, 180.0) == 4


def test_optimal_factor_zoomed_selects_finer():
    # Zoomed view at visible_width_deg=46°
    # ideal = 36000 * 46 / (360 * 2100) ≈ 2.19 → largest ov. ≤ 2.19 → 2
    src = _mock_src(36_000, [2, 4, 8, 16, 32, 64, 128])
    assert _optimal_factor(src, 2100, 46.0) == 2


def test_optimal_factor_fallback_to_native():
    # ideal ≈ 0.24 — no overview small enough → fall back to 1 (native)
    src = _mock_src(1_000, [2, 4, 8])
    assert _optimal_factor(src, 2100, 180.0) == 1


def test_optimal_factor_exact_match():
    # visible_width_deg=90: ideal = 36000 * 90 / (360 * 2100) ≈ 4.29 → 4
    src = _mock_src(36_000, [2, 4, 8, 16])
    assert _optimal_factor(src, 2100, 90.0) == 4


def test_optimal_factor_no_overviews_returns_native():
    # COG with no pre-built overviews → always return 1
    src = _mock_src(10_000, [])
    assert _optimal_factor(src, 2100, 180.0) == 1


# ---------------------------------------------------------------------------
# _visible_width_deg_for_render
# ---------------------------------------------------------------------------

def test_visible_width_full_globe():
    views = [GlobeView(lon=0.0, lat=0.0)]
    assert _visible_width_deg_for_render(views, 2100) == pytest.approx(180.0)


def test_visible_width_multiple_full_globes():
    views = [GlobeView(0, 0), GlobeView(90, 30), GlobeView(180, -15)]
    assert _visible_width_deg_for_render(views, 2100) == pytest.approx(180.0)


def test_visible_width_zoomed():
    view = GlobeView(lon=-0.29, lat=44.85, zoom=4.18)
    expected = 2100 * zoom_to_mpp(4.18, 44.85) / 111_320.0
    assert _visible_width_deg_for_render([view], 2100) == pytest.approx(expected)


def test_visible_width_mixed_returns_minimum():
    """With full-globe and zoomed views, the zoomed (smaller) value is returned."""
    zoomed_view = GlobeView(0.0, 0.0, zoom=4.0)
    full_view   = GlobeView(0.0, 0.0)
    vwd_zoomed  = 2100 * zoom_to_mpp(4.0, 0.0) / 111_320.0
    assert _visible_width_deg_for_render([full_view, zoomed_view], 2100) == pytest.approx(vwd_zoomed)
    assert vwd_zoomed < 180.0  # sanity check


# ---------------------------------------------------------------------------
# _optimal_factor with quality_scale
# ---------------------------------------------------------------------------

def test_optimal_factor_quality_scale_2_lcm10():
    # LCM-10 full globe, qs=2.0: ideal = 8.57/2 = 4.28 → ov ≤ 4.28 → 4
    src = _mock_src(36_000, [2, 4, 8, 16, 32, 64, 128])
    assert _optimal_factor(src, 2100, 180.0, quality_scale=2.0) == 4


def test_optimal_factor_quality_scale_2_bg_cog():
    # BG COG full globe, qs=2.0: ideal = 5.14/2 = 2.57 → ov ≤ 2.57 → 2
    src = _mock_src(21_600, [2, 4, 8, 16, 32, 64])
    assert _optimal_factor(src, 2100, 180.0, quality_scale=2.0) == 2


def test_optimal_factor_quality_scale_1_unchanged():
    # qs=1.0 should give the same result as calling without the argument.
    src = _mock_src(36_000, [2, 4, 8, 16, 32, 64, 128])
    assert _optimal_factor(src, 2100, 180.0, quality_scale=1.0) == \
           _optimal_factor(src, 2100, 180.0)


# ---------------------------------------------------------------------------
# _bbox_for_view
# ---------------------------------------------------------------------------

def test_bbox_for_view_full_globe_returns_none():
    view = GlobeView(lon=10.0, lat=45.0)   # zoom is None
    assert _bbox_for_view(view, 2100) is None


def test_bbox_for_view_zoomed_returns_tuple():
    view = GlobeView(lon=-0.29, lat=44.85, zoom=4.18)
    result = _bbox_for_view(view, 2100)
    assert result is not None
    lon_min, lat_min, lon_max, lat_max = result
    assert lon_min < view.lon < lon_max
    assert lat_min < view.lat < lat_max


def test_bbox_for_view_clamps_to_world_bounds():
    # Extreme northern latitude with large zoom-out should clamp lat to ≤ 90
    view = GlobeView(lon=0.0, lat=80.0, zoom=0.5)
    result = _bbox_for_view(view, 2100)
    assert result is not None
    assert result[1] >= -90.0
    assert result[3] <= 90.0
    assert result[0] >= -180.0
    assert result[2] <= 180.0


def test_bbox_for_view_buffer_widens_bbox():
    view = GlobeView(lon=0.0, lat=0.0, zoom=4.0)
    no_buf  = _bbox_for_view(view, 2100, buffer=0.0)
    with_buf = _bbox_for_view(view, 2100, buffer=0.2)
    assert no_buf is not None and with_buf is not None
    assert with_buf[0] <= no_buf[0]   # lon_min is more negative
    assert with_buf[2] >= no_buf[2]   # lon_max is more positive


# ---------------------------------------------------------------------------
# _render_bbox
# ---------------------------------------------------------------------------

def test_render_bbox_full_globe_returns_none():
    views = [GlobeView(lon=0.0, lat=0.0)]
    assert _render_bbox(views, 2100) is None


def test_render_bbox_mixed_returns_none():
    views = [GlobeView(lon=0.0, lat=0.0), GlobeView(lon=10.0, lat=20.0, zoom=3.0)]
    assert _render_bbox(views, 2100) is None


def test_render_bbox_all_zoomed_returns_union():
    v1 = GlobeView(lon=-10.0, lat=40.0, zoom=4.0)
    v2 = GlobeView(lon= 20.0, lat=50.0, zoom=4.0)
    result = _render_bbox([v1, v2], 2100)
    assert result is not None
    b1 = _bbox_for_view(v1, 2100)
    b2 = _bbox_for_view(v2, 2100)
    assert result[0] == min(b1[0], b2[0])  # type: ignore[index]
    assert result[2] == max(b1[2], b2[2])  # type: ignore[index]


def test_render_bbox_single_zoomed_matches_bbox_for_view():
    view = GlobeView(lon=2.35, lat=48.85, zoom=5.0)
    assert _render_bbox([view], 2100) == _bbox_for_view(view, 2100)
