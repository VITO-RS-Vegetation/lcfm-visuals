"""
flythrough_recorder.py — MapLibre flight-path video recorder.

Drives a headless Chromium browser through a series of zoom/pan waypoints
defined in a TOML config file, captures each fully-rendered frame, and
assembles a 1080×1080 MP4 with libx264.

Usage
-----
    uv run python scripts/flythrough_recorder.py \\
        --config configs/flightpath.toml \\
        --name africa_zoom

Optional overrides
------------------
    --fps 30          Frames per second
    --output path.mp4 Override the output path from the config
    --no-headless     Show the browser window (useful for debugging)
    --tile-timeout 30 Max seconds to wait for tiles to load per frame
"""

from __future__ import annotations

import argparse
import base64
import http.server
import io
import math
import os
import sys
import threading
import time
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # fallback for older Python

import imageio
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render a MapLibre flythrough to MP4.")
    p.add_argument("--config", required=True, help="Path to flightpath TOML config.")
    p.add_argument("--name", required=True, help="Name of the [[flightpath]] entry to render.")
    p.add_argument("--fps", type=float, default=None, help="Override fps from config.")
    p.add_argument("--output", default=None, help="Override output path from config.")
    p.add_argument("--no-headless", action="store_true", help="Show browser window.")
    p.add_argument("--tile-timeout", type=int, default=30,
                   help="Max seconds to wait for tiles per frame (default: 30).")
    p.add_argument("--test-frame", action="store_true",
                   help="Capture only the first waypoint as a PNG and exit.")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(config_path: str, name: str) -> tuple[dict, dict]:
    """Return (settings, flightpath_entry) for the named entry."""
    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    settings = data.get("settings", {})

    entries = data.get("flightpath", [])
    for entry in entries:
        if entry.get("name") == name:
            return settings, entry

    available = [e.get("name", "<unnamed>") for e in entries]
    sys.exit(
        f"No [[flightpath]] entry with name={name!r} found in {config_path}.\n"
        f"Available: {available}"
    )


# ---------------------------------------------------------------------------
# Local HTTP server (avoids CORS errors from file://)
# ---------------------------------------------------------------------------

class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass  # suppress request logs


def start_http_server(root: Path) -> tuple[http.server.HTTPServer, int]:
    """Start a server rooted at *root* on a random free port. Returns (server, port)."""
    os.chdir(root)
    server = http.server.HTTPServer(("127.0.0.1", 0), _QuietHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


# ---------------------------------------------------------------------------
# Easing
# ---------------------------------------------------------------------------

def cosine_ease(t: float) -> float:
    """Map linear t ∈ [0, 1] to eased t via cosine (ease-in-out)."""
    return 0.5 * (1.0 - math.cos(math.pi * t))


# ---------------------------------------------------------------------------
# Frame capture
# ---------------------------------------------------------------------------

def capture_frame(page, tile_timeout: int, settle_s: float = 1.5) -> np.ndarray:
    """
    1. Python-side: sleep briefly to let tile requests start, then poll until
       MapLibre reports all tiles loaded (or timeout).  areTilesLoaded() returns
       True for errored tiles too, so the settle sleep is essential — without it
       we capture before any request even leaves the browser.
    2. JS-side: trigger one repaint and wait for the 'render' event before
       reading the canvas, guaranteeing the WebGL buffer is populated.
    """
    # Step 1 — minimum settle: let tile requests fire and get responses
    time.sleep(settle_s)

    deadline = time.monotonic() + tile_timeout
    while time.monotonic() < deadline:
        ready = page.evaluate(
            "window.map.areTilesLoaded() && !window.map.isMoving()"
        )
        if ready:
            break
        time.sleep(0.2)

    # Step 2 — capture after a genuine render event (short timeout: tiles are ready)
    data_url: str = page.evaluate(
        """() => new Promise((resolve, reject) => {
            const t = setTimeout(
                () => reject(new Error('render event never fired (5s)')), 5000
            );
            window.map.once('render', () => {
                clearTimeout(t);
                resolve(document.querySelector('canvas').toDataURL('image/png'));
            });
            window.map.triggerRepaint();
        })"""
    )
    _, b64 = data_url.split(",", 1)
    img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    return img  # return PIL Image so caller can downscale to output size


# ---------------------------------------------------------------------------
# Star field compositing (Python-side)
# ---------------------------------------------------------------------------

STARS_IMAGE = Path("images/stars_background_chatgpt.png")


def load_stars(width: int, height: int) -> np.ndarray:
    """Return an (H, W, 3) uint8 array loaded from STARS_IMAGE, resized to fit."""
    img = Image.open(STARS_IMAGE).convert("RGB")
    if img.size != (width, height):
        img = img.resize((width, height), Image.LANCZOS)
    return np.array(img)


def composite_stars(
    frame: np.ndarray, stars: np.ndarray, threshold: int = 15
) -> np.ndarray:
    """Blend *stars* into the space (near-black) pixels of *frame*.

    Pixels where max(R,G,B) < threshold are considered empty space and get
    replaced by the corresponding star pixel.  The atmosphere halo pixels
    (horizon-color '#1a3060' = max≈96) are well above the threshold and are
    left untouched.
    """
    mask = frame.max(axis=2) < threshold          # True where space/black
    out = frame.copy()
    out[mask] = stars[mask]
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        sys.exit(f"Config not found: {config_path}")

    settings, entry = load_config(str(config_path), args.name)

    fps          = args.fps or settings.get("fps", 30)
    width        = entry.get("width",  settings.get("width",  1080))
    height       = entry.get("height", settings.get("height", 1080))
    duration_s   = entry.get("duration_s", settings.get("duration_s", 15.0))
    pre_frames   = entry.get("pre_frames",  settings.get("pre_frames",  0))
    post_frames  = entry.get("post_frames", settings.get("post_frames", 0))
    output_path  = Path(args.output or entry.get("output", f"images/flythrough_{args.name}.mp4"))
    waypoints    = entry["waypoints"]

    if len(waypoints) < 2:
        sys.exit("Need at least 2 waypoints.")

    n_segments   = len(waypoints) - 1
    frames_total = round(fps * duration_s)
    # Distribute frames as evenly as possible across segments
    base_frames  = frames_total // n_segments
    extra        = frames_total - base_frames * n_segments
    segment_frames = [base_frames + (1 if i < extra else 0) for i in range(n_segments)]

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load star background image once (resized to output dimensions)
    stars = load_stars(width, height)

    # Start HTTP server rooted at the workspace root (parent of configs/)
    workspace_root = config_path.parent.parent
    server, port = start_http_server(workspace_root)
    url = f"http://127.0.0.1:{port}/html/globe_flythrough.html"
    print(f"[recorder] Serving workspace at http://127.0.0.1:{port}/")
    print(f"[recorder] Output: {output_path}  |  {width}\u00d7{height}  |  {fps} fps  |  {duration_s} s  |  +{pre_frames} pre / +{post_frames} post frames")

    all_frames: list[np.ndarray] = []

    # device_scale_factor=2 makes Playwright report window.devicePixelRatio=2,
    # which causes MapLibre to request tiles one zoom level higher — matching
    # what a HiDPI browser does.  The canvas is 2× the CSS viewport in pixels;
    # we downscale each captured frame back to (width × height) before encoding.
    DPR = 2

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.no_headless)
        context = browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=DPR,
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")

        print("[recorder] Waiting for MapLibre to load…")
        page.wait_for_function("window._mapReady === true", timeout=60_000)
        # Let initial tiles settle
        time.sleep(2)

        if args.test_frame:
            page.evaluate(
                "([z, ln, lt]) => window.map.jumpTo({zoom: z, center: [ln, lt]})",
                [waypoints[0]["zoom"], waypoints[0]["lon"], waypoints[0]["lat"]],
            )
            img = capture_frame(page, args.tile_timeout)
            if img.size != (width, height):
                img = img.resize((width, height), Image.LANCZOS)
            frame_np = composite_stars(np.array(img), stars)
            test_path = output_path.with_suffix(".test_frame.png")
            Image.fromarray(frame_np).save(test_path)
            print(f"[recorder] Test frame saved: {test_path}")
            browser.close()
            server.shutdown()
            return

        def capture_at(wp: dict) -> np.ndarray:
            """Jump to a waypoint, capture, and return a downscaled numpy frame."""
            page.evaluate(
                "([z, ln, lt]) => window.map.jumpTo({zoom: z, center: [ln, lt]})",
                [wp["zoom"], wp["lon"], wp["lat"]],
            )
            img = capture_frame(page, args.tile_timeout)
            if img.size != (width, height):
                img = img.resize((width, height), Image.LANCZOS)
            return composite_stars(np.array(img), stars)

        # ── Pre-roll: static hold on first waypoint ──
        if pre_frames > 0:
            print(f"[recorder] Pre-roll: {pre_frames} static frames at first waypoint")
            hold = capture_at(waypoints[0])
            for _ in range(pre_frames):
                all_frames.append(hold)

        for seg_idx in range(n_segments):
            wp_a = waypoints[seg_idx]
            wp_b = waypoints[seg_idx + 1]
            n_frames = segment_frames[seg_idx]

            print(
                f"[recorder] Segment {seg_idx + 1}/{n_segments}: "
                f"zoom {wp_a['zoom']} → {wp_b['zoom']}, "
                f"{n_frames} frames"
            )

            for i in range(n_frames):
                t_linear = i / max(n_frames - 1, 1)
                t_eased  = cosine_ease(t_linear)

                zoom = wp_a["zoom"] + (wp_b["zoom"] - wp_a["zoom"]) * t_eased
                lat  = wp_a["lat"]  + (wp_b["lat"]  - wp_a["lat"])  * t_eased
                lon  = wp_a["lon"]  + (wp_b["lon"]  - wp_a["lon"])  * t_eased

                page.evaluate(
                    "([z, ln, lt]) => window.map.jumpTo({zoom: z, center: [ln, lt]})",
                    [zoom, lon, lat],
                )

                img = capture_frame(page, args.tile_timeout)
                # Downscale from the 2× physical canvas back to output size
                if img.size != (width, height):
                    img = img.resize((width, height), Image.LANCZOS)
                all_frames.append(composite_stars(np.array(img), stars))

                if (i + 1) % 10 == 0 or i == n_frames - 1:
                    done = sum(segment_frames[:seg_idx]) + i + 1
                    print(f"  frame {done}/{frames_total}")

        # ── Post-roll: static hold on last waypoint ──
        if post_frames > 0:
            print(f"[recorder] Post-roll: {post_frames} static frames at last waypoint")
            hold = capture_at(waypoints[-1])
            for _ in range(post_frames):
                all_frames.append(hold)

        browser.close()

    server.shutdown()

    print(f"[recorder] Writing {len(all_frames)} frames to {output_path}…")
    writer = imageio.get_writer(
        str(output_path),
        format="FFMPEG",
        fps=fps,
        codec="libx264",
        macro_block_size=1,  # avoid auto-resize: 1080 is not divisible by 16
        output_params=["-pix_fmt", "yuv420p", "-crf", "18", "-preset", "slow"],
    )
    for frame in all_frames:
        writer.append_data(frame)
    writer.close()

    print(f"[recorder] Done → {output_path}")


if __name__ == "__main__":
    main()
