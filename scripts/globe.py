#!/usr/bin/env python3
"""Rotating globe using PyVista and a GeoTIFF texture.

Outputs: globe_rotation_fps{FPS}.gif  +  .mp4  (always both)

Dependencies (already in pyproject.toml):
    pyvista rasterio imageio imageio-ffmpeg pillow
"""

from pathlib import Path

import imageio
import numpy as np
import pyvista as pv
import rasterio
from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TIF_PATH = Path("LCM-10_v100_2020_MAP_latlon_with_bg.tif")
OUTPUT_STEM = Path("globe_rotation")  # outputs: globe_rotation_fps{FPS}.gif / .mp4

SPHERE_RESOLUTION = 180  # theta / phi subdivisions (higher = smoother)
WINDOW_SIZE = (896, 896)  # divisible by 16 (avoids ffmpeg resize warning)
DURATION_S = 12  # length of one full rotation in seconds
FPS = 30
N_FRAMES = FPS * DURATION_S  # derived automatically
TILT = True  # True = apply Earth's 23.44 deg axial tilt
BACKGROUND = (
    "white"  # "black", "white", or any CSS colour; used only when no overlay is active
)
START_LON = 0  # longitude (degrees) facing the camera at frame 0; 0 = Greenwich
# ---------------------------------------------------------------------------
# Overlay / compositing  (all optional)
# ---------------------------------------------------------------------------
# Example of the intended result (static background + rotating globe):
#   https://zarr.eopf.copernicus.eu/wp-content/uploads/2026/02/Earth-planet_03a.gif
# Path to a pre-made RGBA PNG that is composited on top of every frame.
# The image must match WINDOW_SIZE.  If None, auto-generation is controlled
# by GENERATE_OVERLAY below.
OVERLAY_PATH: Path | None = None

# When True and OVERLAY_PATH is None, a dark-blue background with a
# feathered circular hole for the globe is generated automatically.
GENERATE_OVERLAY: bool = True

# Background colour for the generated overlay (R, G, B) 0-255.
OVERLAY_COLOR: tuple[int, int, int] = (8, 20, 55)  # deep navy

# Radius (px) of the transparent globe hole in the generated overlay.
# None = auto-estimate from WINDOW_SIZE (≈ 44 % of the shorter side).
GLOBE_RADIUS_PX: int | None = None
# ---------------------------------------------------------------------------


def load_texture(tif_path: Path) -> pv.Texture:
    """Read the GeoTIFF at full resolution and return a PyVista Texture."""
    with rasterio.open(tif_path) as src:
        print(f"  reading {src.width}x{src.height} at full resolution")
        data = src.read()

    # (bands, H, W) -> (H, W, bands). PyVista handles the VTK origin flip internally.
    rgb = np.moveaxis(data, 0, -1).astype(np.uint8)
    return pv.Texture(rgb)


def make_textured_sphere(theta_res: int, phi_res: int) -> pv.PolyData:
    """Build a UV sphere with seamless equirectangular texture coordinates.

    Computing UV from arctan2 causes a discontinuity at the antimeridian
    (u jumps 1->0), which the GPU interpolates across the full texture width.
    Instead, we generate the mesh directly from the (theta, phi) parametric
    grid: seam vertices are duplicated (u=0 on the left side, u=1 on the
    right), so no triangle ever interpolates across the discontinuity.
    """
    # phi  in [0,  pi]: north pole -> south pole
    # theta in [0, 2pi]: west -> east
    phi = np.linspace(0.0, np.pi, phi_res + 1)
    theta = np.linspace(0.0, 2 * np.pi, theta_res + 1)

    # u in [0,1] west->east; v in [1,0] north->south  (matches load_texture convention)
    u_vals = np.linspace(0.0, 1.0, theta_res + 1)
    v_vals = np.linspace(1.0, 0.0, phi_res + 1)

    PHI, THETA = np.meshgrid(phi, theta, indexing="ij")  # (phi_res+1, theta_res+1)
    V, U = np.meshgrid(v_vals, u_vals, indexing="ij")

    x = np.sin(PHI) * np.cos(THETA)
    y = np.sin(PHI) * np.sin(THETA)
    z = np.cos(PHI)

    points = np.column_stack([x.ravel(), y.ravel(), z.ravel()])
    tcoords = np.column_stack([U.ravel(), V.ravel()])

    cols = theta_res + 1
    faces = []
    for j in range(phi_res):
        for i in range(theta_res):
            v0 = j * cols + i  # (phi=j,   theta=i  )
            v1 = j * cols + i + 1  # (phi=j,   theta=i+1)
            v2 = (j + 1) * cols + i  # (phi=j+1, theta=i  )
            v3 = (j + 1) * cols + i + 1  # (phi=j+1, theta=i+1)
            faces += [3, v0, v1, v3, 3, v0, v3, v2]

    mesh = pv.PolyData(
        np.array(points, dtype=np.float32),
        np.array(faces, dtype=np.int64),
    )
    mesh.active_texture_coordinates = tcoords.astype(np.float32)
    # Explicit normals prevent a lighting seam at the antimeridian.
    # VTK's auto-generated smooth normals are skewed at the duplicated seam
    # vertices because each side only "sees" faces on one half.
    mesh.point_data["Normals"] = np.array(points, dtype=np.float32)
    return mesh


def make_overlay(
    size: tuple[int, int],
    globe_radius_px: int | None = None,
    color: tuple[int, int, int] = (8, 20, 55),
) -> Image.Image:
    """Return an RGBA image: solid *color* background with a circular hole
    centred in the frame — the hole reveals the globe underneath.

    The renderer background is set to the same *color*, so PyVista's own
    edge anti-aliasing produces a seamless blend without any extra feathering.

    Args:
        size: (width, height) in pixels; should match WINDOW_SIZE.
        globe_radius_px: radius of the transparent hole.  ``None`` = 44 % of
            the shorter dimension (good default for the default camera setup).
        color: RGB background colour (default: deep navy).

    Returns:
        RGBA ``PIL.Image``: transparent inside the circle, opaque outside.
    """
    w, h = size
    cx, cy = w // 2, h // 2
    if globe_radius_px is None:
        globe_radius_px = int(min(w, h) * 0.44)

    # Draw a filled white circle on a black canvas → white = hole area
    circle_mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(circle_mask)
    r = globe_radius_px
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)

    # Invert: hole area (white circle) becomes transparent (0), background opaque (255).
    alpha = Image.fromarray(255 - np.array(circle_mask), mode="L")

    overlay = Image.new("RGBA", size, (*color, 0))
    overlay.putalpha(alpha)
    return overlay


def main():
    print(f"Loading texture from {TIF_PATH} ...")
    texture = load_texture(TIF_PATH)

    sphere = make_textured_sphere(
        theta_res=SPHERE_RESOLUTION * 2,
        phi_res=SPHERE_RESOLUTION,
    )

    plotter = pv.Plotter(off_screen=True, window_size=list(WINDOW_SIZE))
    # Background is finalised after overlay detection (see below).
    plotter.set_background(BACKGROUND)

    actor = plotter.add_mesh(sphere, texture=texture, smooth_shading=True)

    if TILT:
        # Tip the north pole 23.44 deg toward the camera (+X axis) so the
        # axial tilt is visible. The subsequent RotateZ calls then spin the
        # globe around the orbital-plane normal, reproducing Earth's motion.
        actor.RotateY(23.44)

    # Rotate so START_LON faces the camera at frame 0.
    # theta=0 on the sphere maps to u=0 = -180° lon; offset accordingly.
    actor.RotateZ(-((START_LON + 180) % 360))

    # Camera: sit on the +X axis, look at origin, Z is up
    plotter.camera.position = (4.5, 0.0, 0.0)
    plotter.camera.focal_point = (0.0, 0.0, 0.0)
    plotter.camera.up = (0.0, 0.0, 1.0)

    # ------------------------------------------------------------------
    # Overlay setup
    # ------------------------------------------------------------------
    overlay: Image.Image | None = None

    if OVERLAY_PATH is not None:
        print(f"Loading overlay from {OVERLAY_PATH} ...")
        overlay = Image.open(OVERLAY_PATH).convert("RGBA")
    elif GENERATE_OVERLAY:
        print(f"Generating dark-blue overlay ({WINDOW_SIZE[0]}x{WINDOW_SIZE[1]}) ...")
        overlay = make_overlay(
            size=WINDOW_SIZE,
            globe_radius_px=GLOBE_RADIUS_PX,
            color=OVERLAY_COLOR,
        )
        _ov_path = OUTPUT_STEM.with_name(f"{OUTPUT_STEM.stem}_overlay.png")
        overlay.save(_ov_path)
        print(f"  saved generated overlay -> {_ov_path}")

    # When an overlay is active the PyVista background must match the overlay's
    # solid colour.  PyVista anti-aliases the sphere edge against the background,
    # so mismatched colours leave a visible "halo" of the background colour at
    # the rim of the globe.  Matching them makes the seam invisible.
    if overlay is not None:
        plotter.set_background(tuple(c / 255.0 for c in OVERLAY_COLOR))

    def composite(raw_frame: np.ndarray) -> np.ndarray:
        """Alpha-composite the overlay on top of the rendered globe frame."""
        if overlay is None:
            return raw_frame
        globe_img = Image.fromarray(raw_frame).convert("RGBA")
        result = Image.alpha_composite(globe_img, overlay)
        return np.array(result.convert("RGB"))

    # ------------------------------------------------------------------

    stem = f"{OUTPUT_STEM.stem}_fps{FPS}"
    gif_path = OUTPUT_STEM.with_name(f"{stem}.gif")
    mp4_path = OUTPUT_STEM.with_name(f"{stem}.mp4")
    print(
        f"Rendering {N_FRAMES} frames ({DURATION_S}s @ {FPS} fps) -> {gif_path}  +  {mp4_path}"
    )

    step = 360.0 / N_FRAMES
    with (
        imageio.get_writer(str(gif_path), mode="I", fps=FPS, loop=0) as gif_w,
        imageio.get_writer(str(mp4_path), fps=FPS, quality=9) as mp4_w,
    ):
        for i in range(N_FRAMES):
            plotter.render()
            frame = composite(plotter.screenshot(return_img=True))
            gif_w.append_data(frame)
            mp4_w.append_data(frame)
            actor.RotateZ(step)
            if (i + 1) % 20 == 0:
                print(f"  frame {i + 1}/{N_FRAMES}")

    plotter.close()
    print(f"Done -- saved {gif_path} and {mp4_path}")


if __name__ == "__main__":
    main()
