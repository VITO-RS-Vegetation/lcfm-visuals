"""Unit tests for orthographic_globe helper functions.

All tests are pure-Python (no network access, no COG downloads).

Integration tests that download COG data are marked with
``@pytest.mark.integration``.  They are excluded from the default run; opt in
with::

    pytest -m integration
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orthographic_globe import (
    GlobeView,
    _optimal_factor,
    _parse_globe_views,
    _visible_width_deg_for_render,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent.parent / "configs" / "globes.toml"


# ---------------------------------------------------------------------------
# GlobeView dataclass
# ---------------------------------------------------------------------------

def test_globe_view_equality():
    assert GlobeView(lon=-90.0, lat=15.0) == GlobeView(lon=-90.0, lat=15.0)
    assert GlobeView(lon=-90.0, lat=15.0) != GlobeView(lon=60.0, lat=25.0)


# ---------------------------------------------------------------------------
# TOML config
# ---------------------------------------------------------------------------

def test_config_has_three_renders():
    with open(CONFIG_PATH, "rb") as fh:
        config = tomllib.load(fh)
    assert len(config.get("render", [])) == 3


def test_config_render_names():
    with open(CONFIG_PATH, "rb") as fh:
        config = tomllib.load(fh)
    names = {r["name"] for r in config["render"]}
    assert names == {"1_globe_europe", "2_globes", "3_globes"}


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


def test_parse_globe_views_1_globe_config():
    with open(CONFIG_PATH, "rb") as fh:
        config = tomllib.load(fh)
    entry = next(r for r in config["render"] if r.get("name") == "1_globe_europe")
    views = _parse_globe_views(entry)
    assert len(views) == 1


def test_parse_globe_views_2_globes_config():
    with open(CONFIG_PATH, "rb") as fh:
        config = tomllib.load(fh)
    entry = next(r for r in config["render"] if r.get("name") == "2_globes")
    views = _parse_globe_views(entry)
    assert len(views) == 2


def test_parse_globe_views_3_globes_config():
    with open(CONFIG_PATH, "rb") as fh:
        config = tomllib.load(fh)
    entry = next(r for r in config["render"] if r.get("name") == "3_globes")
    views = _parse_globe_views(entry)
    assert len(views) == 3


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
    # Narrow visible width (46°) selects a finer overview
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
# Icon config keys
# ---------------------------------------------------------------------------

def test_config_1_globe_europe_has_icon_output():
    with open(CONFIG_PATH, "rb") as fh:
        config = tomllib.load(fh)
    entry = next(r for r in config["render"] if r.get("name") == "1_globe_europe")
    assert "icon_output" in entry
    assert entry["icon_output"].endswith(".png")


def test_config_1_globe_europe_icon_size_px():
    with open(CONFIG_PATH, "rb") as fh:
        config = tomllib.load(fh)
    entry = next(r for r in config["render"] if r.get("name") == "1_globe_europe")
    assert "icon_size_px" in entry
    assert isinstance(entry["icon_size_px"], int)
    assert entry["icon_size_px"] > 0


def test_config_icon_size_single_integer():
    """icon_size_px must be a single integer (not a list), guaranteeing square output."""
    with open(CONFIG_PATH, "rb") as fh:
        config = tomllib.load(fh)
    for entry in config.get("render", []):
        if "icon_size_px" in entry:
            assert isinstance(entry["icon_size_px"], int), (
                f"icon_size_px in '{entry.get('name')}' must be a plain int"
            )
