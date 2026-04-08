#!/usr/bin/env python3
"""Build an interactive HTML globe from a PNG texture.

Usage:
    python build_globe_html.py

Output:
    globe_interactive.html

    - TEXTURE_SRC = URL  → tiny HTML (~0.6 MB); viewer needs internet.
    - TEXTURE_SRC = Path → self-contained HTML (~15 MB); fully offline.

Phase 1 (first run only): downloads Three.js + OrbitControls to vendor/
         — internet connection required only for this step.
Phase 2: resolves texture — URL is used directly; local Path is base64-encoded.
Phase 3: assembles and writes globe_interactive.html.
"""

import base64
import math
import shutil
from pathlib import Path
from urllib.request import urlopen

# ---------------------------------------------------------------------------
# Config (mirrors globe.py where applicable)
# ---------------------------------------------------------------------------
# TEXTURE_SRC: set to a URL for a small online HTML, or a local Path for a
# fully self-contained offline HTML (~15 MB with the base64-encoded PNG).
TEXTURE_SRC: str | Path = (
    "https://raw.githubusercontent.com/JorisCod/lcm-assets/main/"
    "assets/LCM-10_v100_2020_MAP_lat-lon_bg.png"
)
OUTPUT_HTML = Path("results/globe_interactive.html")
VENDOR_DIR = Path("vendor")

TILT: bool = True                                    # apply Earth's 23.44 deg axial tilt
START_LON: int = 0                                   # longitude facing the camera at frame 0
OVERLAY_COLOR: tuple[int, int, int] = (8, 20, 55)   # deep navy background (matches globe.py)
ROTATION_PERIOD_S: float = 12.0                      # seconds per full rotation

# Three.js r128 — UMD build + non-module OrbitControls (no ES-module complexity)
_THREE_VERSION = "0.128.0"
_CDN = f"https://cdn.jsdelivr.net/npm/three@{_THREE_VERSION}"
_VENDOR_FILES: dict[str, str] = {
    "three.min.js": f"{_CDN}/build/three.min.js",
    "OrbitControls.js": f"{_CDN}/examples/js/controls/OrbitControls.js",
}
# ---------------------------------------------------------------------------


def ensure_vendor() -> None:
    """Download JS vendor files into vendor/ if not already present."""
    VENDOR_DIR.mkdir(exist_ok=True)
    for filename, url in _VENDOR_FILES.items():
        dest = VENDOR_DIR / filename
        if dest.exists():
            print(f"  vendor/{filename}: already present ({dest.stat().st_size // 1024} KB)")
            continue
        print(f"  downloading {url} ...")
        with urlopen(url) as resp, dest.open("wb") as fh:
            shutil.copyfileobj(resp, fh)
        print(f"    -> saved vendor/{filename} ({dest.stat().st_size // 1024} KB)")


def resolve_texture(src: str | Path) -> str:
    """Return the texture URI to embed in the HTML.

    - str (URL): returned as-is; viewer needs internet to load it.
    - Path:      base64-encoded to a data URI; fully offline.
    """
    if isinstance(src, str):  # URL
        print(f"  texture URL: {src}")
        print("    -> will be fetched by the viewer's browser (internet required)")
        return src
    size_kb = src.stat().st_size // 1024
    print(f"  {src}  ({size_kb} KB)  ...")
    b64 = base64.b64encode(src.read_bytes()).decode("ascii")
    print(f"    -> base64: {len(b64) // 1024} KB")
    return f"data:image/png;base64,{b64}"


def build_html(texture_uri: str, three_js: str, orbit_js: str) -> str:
    r, g, b = OVERLAY_COLOR
    bg_hex = f"#{r:02x}{g:02x}{b:02x}"
    bg_int = f"0x{(r << 16 | g << 8 | b):06x}"

    # Axial tilt: rotate tiltGroup around world X so that +Y (north pole) leans toward
    # the camera (+Z). Positive X rotation (right-hand rule) takes +Y toward +Z. ✓
    tilt_rad = f"{23.44 * math.pi / 180:.6f}" if TILT else "0.0"

    # Initial Y rotation (degrees) to bring START_LON to face the camera.
    # Three.js SphereGeometry default: lon=0° (u=0.5) sits at +X in local space.
    # Camera is at +Z. To put lon=L at +Z: rotation.y = -(90 + L) degrees.
    initial_rot_y_deg = str(-(90 + START_LON))
    rot_period = str(ROTATION_PERIOD_S)
    three_ver = _THREE_VERSION

    # Use TMPL_ placeholders to avoid f-string escaping of JS curly braces.
    # The texture is injected as a hidden <img> element rather than a JS string
    # literal, because browsers parse large data URIs in HTML attributes without
    # the memory/freezing issues that arise from 13+ MB JS string literals.
    template = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LCM-10 Interactive Globe</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { width: 100%; height: 100%; overflow: hidden; background: TMPL_BG_HEX; }
  canvas { display: block; position: fixed; inset: 0; }
  #globe-tex { display: none; }

  /* Vignette: darkens edges to frame the globe on the navy background */
  #vignette {
    position: fixed; inset: 0; pointer-events: none;
    background: radial-gradient(
      circle,
      transparent 38%,
      rgba(TMPL_R,TMPL_G,TMPL_B,0.55) 65%,
      rgba(TMPL_R,TMPL_G,TMPL_B,0.95) 86%
    );
  }

  /* Loading indicator */
  #loading {
    position: fixed; inset: 0; z-index: 20;
    display: flex; align-items: center; justify-content: center;
    color: rgba(255,255,255,0.65); font: 16px/1 system-ui, sans-serif;
    pointer-events: none;
  }

  /* Hint bar */
  #hint {
    position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
    color: rgba(255,255,255,0.42); font: 13px/1.6 system-ui, sans-serif;
    pointer-events: none; text-align: center; white-space: nowrap;
    transition: opacity 1.2s ease; z-index: 10;
  }
  #hint.hidden { opacity: 0; }

  /* Rotation toggle button */
  #spin-btn {
    position: fixed; bottom: 22px; right: 24px; z-index: 30;
    background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.28);
    color: #fff; font: 13px/1 system-ui, sans-serif;
    padding: 7px 14px; border-radius: 6px; cursor: pointer;
    backdrop-filter: blur(4px); transition: background 0.2s;
    user-select: none;
  }
  #spin-btn:hover { background: rgba(255,255,255,0.22); }
</style>
</head>
<body>
<!-- Texture embedded as an HTML img element; avoids JS-string-literal parsing
     freeze for large base64 data URIs. The <script> below reads it via
     document.getElementById('globe-tex'). -->
<img id="globe-tex" src="TMPL_TEXTURE_URI" crossorigin="anonymous" alt="">
<div id="vignette"></div>
<div id="loading">Loading texture&hellip;</div>
<div id="hint">Drag to orbit &nbsp;&middot;&nbsp; Scroll to zoom</div>
<button id="spin-btn" title="Toggle rotation (Space)">&#9646;&#9646; Pause</button>

<script>/* three.min.js r TMPL_THREE_VER */
TMPL_THREE_JS
</script>
<script>/* OrbitControls r TMPL_THREE_VER */
TMPL_ORBIT_JS
</script>
<script>
"use strict";

// ── Config ────────────────────────────────────────────────────────────────────
var BG_COLOR          = TMPL_BG_INT;
var TILT_RAD          = TMPL_TILT_RAD;        // axial tilt in radians
var INITIAL_ROT_Y_DEG = TMPL_ROT_Y_DEG;       // bring START_LON to face camera (+Z)
var ROT_PERIOD_S      = TMPL_ROT_PERIOD;       // seconds per full rotation

// ── Scene ─────────────────────────────────────────────────────────────────────
var scene = new THREE.Scene();
scene.background = new THREE.Color(BG_COLOR);

var camera = new THREE.PerspectiveCamera(40, innerWidth / innerHeight, 0.01, 100);
camera.position.set(0, 0, 3.0);

var renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
// Insert canvas before all other body children so UI elements sit on top naturally.
document.body.insertBefore(renderer.domElement, document.body.firstChild);

// ── Lighting ──────────────────────────────────────────────────────────────────
// No lights needed — MeshBasicMaterial renders the texture uniformly.

// ── Globe (built once the img element has decoded) ────────────────────────────
// tiltGroup applies Earth's axial tilt: rotate around world X so +Y (north pole)
// leans toward the camera (+Z axis). Children spin around the tilted Y axis.
var tiltGroup = new THREE.Group();
tiltGroup.rotation.x = TILT_RAD;
scene.add(tiltGroup);

var spinGroup = new THREE.Group();
tiltGroup.add(spinGroup);

var globe;   // assigned in initGlobe()

function initGlobe(imgEl) {
  var texture = new THREE.Texture(imgEl);
  texture.needsUpdate = true;
  texture.wrapS = THREE.RepeatWrapping;  // seamless horizontal wrap at antimeridian

  var geometry = new THREE.SphereGeometry(1, 128, 64);
  var material = new THREE.MeshBasicMaterial({ map: texture });
  globe = new THREE.Mesh(geometry, material);

  // Bring START_LON to face the camera at frame 0.
  // Three.js SphereGeometry: lon=0° (u=0.5) is at local +X; camera at world +Z.
  // Required initial rotation: -(90 + START_LON) degrees around Y.
  globe.rotation.y = THREE.MathUtils.degToRad(INITIAL_ROT_Y_DEG);
  spinGroup.add(globe);
  document.getElementById('loading').style.display = 'none';
}

var imgEl = document.getElementById('globe-tex');
if (imgEl.complete && imgEl.naturalWidth > 0) {
  initGlobe(imgEl);
} else {
  imgEl.addEventListener('load', function () { initGlobe(imgEl); });
}

// ── Controls ──────────────────────────────────────────────────────────────────
var controls = new THREE.OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor  = 0.06;
controls.rotateSpeed    = 0.6;
controls.zoomSpeed      = 0.8;
controls.minDistance    = 1.05;   // cannot zoom inside the globe
controls.maxDistance    = 12.0;
controls.enablePan      = true;

// ── Auto-rotation ─────────────────────────────────────────────────────────────
// Positive Y increment = globe rotates counterclockwise from north pole,
// matching Earth's prograde rotation (west-to-east).
// Flip the sign here if the direction looks wrong in your browser.
var spinning = true;
var ROT_SPEED_RAD = (2 * Math.PI) / ROT_PERIOD_S;  // rad/s

var spinBtn = document.getElementById('spin-btn');
function toggleSpin() {
  spinning = !spinning;
  spinBtn.innerHTML = spinning ? '&#9646;&#9646; Pause' : '&#9654; Play';
}
spinBtn.addEventListener('click', toggleSpin);
window.addEventListener('keydown', function (e) {
  if (e.code === 'Space') { e.preventDefault(); toggleSpin(); }
});

window.addEventListener('resize', function () {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

// ── Render loop ───────────────────────────────────────────────────────────────
var clock = new THREE.Clock();
(function animate() {
  requestAnimationFrame(animate);
  var dt = clock.getDelta();
  if (spinning && globe) globe.rotation.y += ROT_SPEED_RAD * dt;
  controls.update();
  renderer.render(scene, camera);
})();

// ── Hint auto-hide ────────────────────────────────────────────────────────────
setTimeout(function () {
  document.getElementById('hint').classList.add('hidden');
}, 4000);
</script>
</body>
</html>"""

    return (template
            .replace("TMPL_BG_HEX", bg_hex)
            .replace("TMPL_BG_INT", bg_int)
            .replace("TMPL_THREE_VER", three_ver)
            .replace("TMPL_THREE_JS", three_js)
            .replace("TMPL_ORBIT_JS", orbit_js)
            .replace("TMPL_TILT_RAD", tilt_rad)
            .replace("TMPL_ROT_Y_DEG", initial_rot_y_deg)
            .replace("TMPL_ROT_PERIOD", rot_period)
            .replace("TMPL_TEXTURE_URI", texture_uri)
            # Single-letter tokens last — must not prefix any other token name
            .replace("TMPL_R", str(r))
            .replace("TMPL_G", str(g))
            .replace("TMPL_B", str(b)))


def main() -> None:
    print("=== build_globe_html ===")

    print("\nPhase 1 — vendor JS assets")
    ensure_vendor()

    print("\nPhase 2 — texture")
    texture_uri = resolve_texture(TEXTURE_SRC)

    print("\nPhase 3 — assembling HTML")
    three_js = (VENDOR_DIR / "three.min.js").read_text(encoding="utf-8")
    orbit_js = (VENDOR_DIR / "OrbitControls.js").read_text(encoding="utf-8")
    html = build_html(texture_uri, three_js, orbit_js)

    OUTPUT_HTML.write_text(html, encoding="utf-8")
    size_mb = OUTPUT_HTML.stat().st_size / 1_048_576
    print(f"\nDone -> {OUTPUT_HTML}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
