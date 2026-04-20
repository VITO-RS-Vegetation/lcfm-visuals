"""Pytest configuration for orthographic_globe tests.

Adds scripts/ to sys.path and pre-mocks heavy rendering dependencies
(cartopy, matplotlib, numpy, rasterio) so the pure-Python helper functions
can be imported and tested without those packages being installed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Mock heavy rendering deps before importing orthographic_globe so that the
# pure-Python helpers (GlobeView, parse_maplibre_hash, etc.) are importable
# in environments that don't have cartopy / matplotlib / rasterio installed.
# ---------------------------------------------------------------------------

# numpy needs special treatment: pytest.approx calls isinstance(val, np.bool_)
# so np.bool_ must be a real type (not a MagicMock) to avoid TypeError.
_numpy_mock = MagicMock()
_numpy_mock.bool_    = bool
_numpy_mock.floating = float
sys.modules["numpy"] = _numpy_mock

_MOCKED_MODULES = [
    "cartopy",
    "cartopy.crs",
    "cartopy.feature",
    "matplotlib",
    "matplotlib.pyplot",
    "rasterio",
    "rasterio.enums",
    "rasterio.windows",
]
for _mod in _MOCKED_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# Make `from rasterio.enums import Resampling` resolve to a MagicMock attr.
sys.modules["rasterio.enums"].Resampling = MagicMock()

# ---------------------------------------------------------------------------
# Add scripts/ to sys.path so `import orthographic_globe` works.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
