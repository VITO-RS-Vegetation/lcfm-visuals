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

import pytest

from orthographic_globe import (
    GlobeView,
    _parse_globe_views,
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
