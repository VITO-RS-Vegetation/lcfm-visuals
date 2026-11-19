#!/usr/bin/env python3
"""Rotating globe animation of multi-annual LCM-10 land cover (MP4, optional GIF).

The globe rotates continuously and crossfades to the next annual map
(e.g. 2020 → 2021 → … → 2024) every ``turns_per_year`` turns (1.0 = one full
turn per year, 0.5 = half a turn) without interrupting the rotation.
With ``loop = true`` the last year fades back into the first, so the video
loops seamlessly when the total number of turns is whole.

Textures are the precomputed DEM-shaded, equirectangular LCM-10 PNGs in
``input/`` (approach A).  The globe is rendered *unlit*: the relief is already
baked into the imagery, so engine lighting would add a second, conflicting
shading.  A mild, rotation-independent limb darkening gives depth instead.

Run (all renders in the config):
    uv run python scripts/rotating_globe.py --config configs/rotating_globe.toml

Fast iteration — one 360° turn centred on the first year change:
    uv run python scripts/rotating_globe.py --name lcm10_2020_2024 --only-transition
"""

from __future__ import annotations

import argparse
import dataclasses
import math
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import imageio
import numpy as np
import pyvista as pv
from PIL import Image, ImageDraw, ImageFont

DEFAULT_CONFIG = Path("configs/rotating_globe.toml")
VIEW_ANGLE_DEG = 30.0  # VTK default vertical camera view angle


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass
class RenderSettings:
    """One ``[[render]]`` entry merged with ``[global]`` defaults."""

    name: str = "rotating_globe"
    output: str = "images/rotating_globe.mp4"
    input_pattern: str = (
        "input/LCFM_LCM-10_V200_{year}_GLOBAL_RELIEF_MULTISCALE_8000x4000_NASA.png"
    )
    years: list[int] = field(default_factory=lambda: [2020, 2021, 2022, 2023, 2024])
    window_size: int = 1080
    fps: int = 30
    rotation_s: float = 15.0
    crossfade_s: float = 1.0
    loop: bool = True
    tilt_deg: float = 23.44
    start_lon: float = 15.0
    camera_distance: float = 5.0
    sphere_resolution: int = 180
    limb_darkening: float = 0.25
    background_color: list[int] = field(default_factory=lambda: [4, 6, 16])
    background_image: str = "images/stars_background_chatgpt.png"
    atmosphere_glow: float = 0.5
    title: str = "LCM-10 land cover"
    show_labels: bool = True
    gif: bool = False
    crf: int = 20
    turns_per_year: float = 1.0
    satellites: bool = False
    orbits_per_turn: float = 2.0
    show_swath: bool = True
    swath_trail_s: float = 2.0
    satellite_size_px: int = 52

    @classmethod
    def from_config(cls, global_cfg: dict, entry: dict) -> RenderSettings:
        """Merge ``entry`` over ``global_cfg``; unknown keys raise ``ValueError``."""
        merged = {**global_cfg, **entry}
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = sorted(set(merged) - known)
        if unknown:
            raise ValueError(f"Unknown setting(s) in config: {', '.join(unknown)}")
        return cls(**merged)

    @property
    def frames_per_rotation(self) -> int:
        return round(self.rotation_s * self.fps)

    @property
    def frames_per_year(self) -> int:
        return round(self.turns_per_year * self.frames_per_rotation)

    @property
    def crossfade_frames(self) -> int:
        return round(self.crossfade_s * self.fps)

    def input_path(self, year: int) -> Path:
        return Path(self.input_pattern.format(year=year))


def load_config(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


# ---------------------------------------------------------------------------
# Frame schedule (pure Python)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameState:
    """What to draw for one output frame.

    ``blend`` is the weight of ``to_idx``; outside a transition
    ``from_idx == to_idx`` and ``blend == 0``.
    """

    index: int
    angle_deg: float
    from_idx: int
    to_idx: int
    blend: float

    @property
    def in_transition(self) -> bool:
        return self.from_idx != self.to_idx


def smoothstep(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def frame_schedule(
    n_years: int,
    frames_per_year: int,
    crossfade_frames: int,
    loop: bool = True,
    frames_per_rotation: int | None = None,
) -> list[FrameState]:
    """Return one :class:`FrameState` per frame for ``n_years`` years.

    Year boundaries fall every ``frames_per_year`` frames; the globe turns 360°
    every ``frames_per_rotation`` frames (default: one turn per year).
    Each crossfade is centred on its boundary so the rotation never pauses.
    With ``loop`` the boundary at the start/end of the video fades from the
    last year into the first, making frame ``N-1 → 0`` seamless (the
    orientation only matches too if the total number of turns is whole).
    """
    if frames_per_rotation is None:
        frames_per_rotation = frames_per_year
    if n_years < 1:
        raise ValueError("need at least one year")
    if frames_per_year < 1 or frames_per_rotation < 1:
        raise ValueError("frames_per_year and frames_per_rotation must be >= 1")
    if not 0 <= crossfade_frames <= frames_per_year:
        raise ValueError("crossfade_frames must be within [0, frames_per_year]")

    states = []
    for i in range(n_years * frames_per_year):
        angle = 360.0 * i / frames_per_rotation
        year = i // frames_per_year
        m = math.floor(i / frames_per_year + 0.5)  # nearest boundary
        has_boundary = n_years > 1 and (loop or 0 < m < n_years)
        w = 0.0
        if crossfade_frames and has_boundary:
            w = (i - m * frames_per_year + crossfade_frames / 2 + 0.5) / crossfade_frames
        if 0.0 < w < 1.0:
            states.append(
                FrameState(i, angle, (m - 1) % n_years, m % n_years, smoothstep(w))
            )
        else:
            states.append(FrameState(i, angle, year, year, 0.0))
    return states


def transition_preview_range(
    frames_per_year: int, frames_per_rotation: int | None = None
) -> range:
    """One full rotation centred on the first year change (frame ``frames_per_year``)."""
    if frames_per_rotation is None:
        frames_per_rotation = frames_per_year
    start = max(0, frames_per_year - frames_per_rotation // 2)
    return range(start, start + frames_per_rotation)


# ---------------------------------------------------------------------------
# Geometry & textures
# ---------------------------------------------------------------------------


def make_textured_sphere(theta_res: int, phi_res: int) -> pv.PolyData:
    """Build a UV sphere with seamless equirectangular texture coordinates.

    Computing UV from arctan2 causes a discontinuity at the antimeridian
    (u jumps 1->0), which the GPU interpolates across the full texture width.
    Instead, we generate the mesh directly from the (theta, phi) parametric
    grid: seam vertices are duplicated (u=0 on the left side, u=1 on the
    right), so no triangle ever interpolates across the discontinuity.
    """
    # phi  in [0,  pi]: north pole -> south pole
    # theta in [0, 2pi]: west -> east (theta=0 is lon -180)
    phi = np.linspace(0.0, np.pi, phi_res + 1)
    theta = np.linspace(0.0, 2 * np.pi, theta_res + 1)
    u_vals = np.linspace(0.0, 1.0, theta_res + 1)
    v_vals = np.linspace(1.0, 0.0, phi_res + 1)

    PHI, THETA = np.meshgrid(phi, theta, indexing="ij")
    V, U = np.meshgrid(v_vals, u_vals, indexing="ij")
    points = np.column_stack(
        [
            (np.sin(PHI) * np.cos(THETA)).ravel(),
            (np.sin(PHI) * np.sin(THETA)).ravel(),
            np.cos(PHI).ravel(),
        ]
    ).astype(np.float32)

    cols = theta_res + 1
    j, i = np.meshgrid(np.arange(phi_res), np.arange(theta_res), indexing="ij")
    v0 = (j * cols + i).ravel()
    v1, v2, v3 = v0 + 1, v0 + cols, v0 + cols + 1
    three = np.full_like(v0, 3)
    faces = np.column_stack([three, v0, v1, v3, three, v0, v3, v2]).ravel()

    mesh = pv.PolyData(points, faces.astype(np.int64))
    mesh.active_texture_coordinates = np.column_stack(
        [U.ravel(), V.ravel()]
    ).astype(np.float32)
    # Explicit normals avoid a shading seam at the duplicated antimeridian vertices.
    mesh.point_data["Normals"] = points
    return mesh


def load_texture(path: Path) -> pv.Texture:
    """Load an equirectangular RGB image as a mipmapped, filtered texture."""
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(path) as im:
        rgb = np.asarray(im.convert("RGB"))
    tex = pv.Texture(rgb)
    # The globe shows the 8k texture at <1k px: without mipmaps it shimmers.
    tex.SetInterpolate(True)
    tex.SetMipmap(True)
    tex.SetMaximumAnisotropicFiltering(16)
    return tex


def globe_matrix(angle_deg: float, tilt_deg: float, start_lon: float) -> np.ndarray:
    """4x4 model matrix: spin about the polar axis, then tilt toward the camera.

    The camera sits on +X; ``start_lon`` faces it at ``angle_deg == 0``.
    Increasing ``angle_deg`` turns the Earth eastward (as seen from space).
    """
    spin = math.radians(angle_deg - (start_lon + 180.0))
    tilt = math.radians(tilt_deg)
    cz, sz = math.cos(spin), math.sin(spin)
    cy, sy = math.cos(tilt), math.sin(tilt)
    rz = np.array([[cz, -sz, 0, 0], [sz, cz, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
    ry = np.array([[cy, 0, sy, 0], [0, 1, 0, 0], [-sy, 0, cy, 0], [0, 0, 0, 1]])
    return ry @ rz


def globe_radius_px(window_size: int, camera_distance: float) -> float:
    """Screen radius of the unit sphere's silhouette (perspective camera)."""
    half_angle = math.asin(1.0 / camera_distance)
    return (window_size / 2) * math.tan(half_angle) / math.tan(
        math.radians(VIEW_ANGLE_DEG / 2)
    )


# ---------------------------------------------------------------------------
# 2-D compositing layers (computed once)
# ---------------------------------------------------------------------------


def disc_layers(size: int, radius: float, limb_darkening: float):
    """Return (coverage mask, limb factor) as float32 HxW arrays."""
    c = (size - 1) / 2
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    r = np.hypot(xx - c, yy - c)
    mask = np.clip(radius - r + 0.5, 0.0, 1.0)
    mu = np.sqrt(np.clip(1.0 - (r / radius) ** 2, 0.0, 1.0))
    limb = 1.0 - limb_darkening * (1.0 - mu)
    return mask, limb.astype(np.float32), r


def make_background(s: RenderSettings, r: np.ndarray, radius: float) -> np.ndarray:
    """Static background (stars or flat colour) plus a soft atmosphere glow."""
    size = s.window_size
    if s.background_image:
        with Image.open(s.background_image) as im:
            bg = np.asarray(
                im.convert("RGB").resize((size, size), Image.LANCZOS), dtype=np.float32
            )
    else:
        bg = np.empty((size, size, 3), np.float32)
        bg[:] = s.background_color
    if s.atmosphere_glow > 0:
        falloff = np.exp(-np.clip(r - radius, 0, None) / (0.035 * radius))
        glow = s.atmosphere_glow * falloff * (r >= radius - 1)
        bg += glow[..., None] * np.array([90, 150, 255], np.float32)
    return np.clip(bg, 0, 255)


def _font(size: int, bold: bool) -> ImageFont.ImageFont:
    names = ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


class LabelLayers:
    """Premultiplied RGBA label sprites, cropped to a shared box per element.

    ``year[k]`` is the big year number and ``timeline[k]`` the 2020…2024 strip
    with year ``k`` highlighted; ``title`` is static.  The three elements never
    overlap, so each is composited independently on its own small crop.
    """

    def __init__(self, s: RenderSettings, indices: list[int]):
        size = s.window_size
        self.size = size
        margin = round(0.035 * size)
        year_font = _font(round(0.085 * size), bold=True)
        tl_size = round(0.028 * size)
        tl_bold, tl_regular = _font(tl_size, True), _font(tl_size, False)

        def canvas():
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            return img, ImageDraw.Draw(img)

        years = {}
        for k in indices:
            img, draw = canvas()
            draw.text((margin, margin), str(s.years[k]), font=year_font, fill="white")
            years[k] = img

        timelines = {}
        texts = [str(y) for y in s.years]
        for k in indices:
            img, draw = canvas()
            widths = [draw.textlength(t, font=tl_bold) for t in texts]
            gap = 0.045 * size
            x = (size - (sum(widths) + gap * (len(texts) - 1))) / 2
            y = size - margin - tl_size
            for j, (text, w) in enumerate(zip(texts, widths)):
                if j == k:
                    draw.text((x, y), text, font=tl_bold, fill="white")
                    bar_y = y + tl_size * 1.25
                    draw.rectangle([x, bar_y, x + w, bar_y + max(2, size // 360)], fill="white")
                else:
                    draw.text((x, y), text, font=tl_regular, fill=(130, 140, 160, 255))
                x += w + gap
            timelines[k] = img

        self.year_box, self.year = self._crop(years)
        self.timeline_box, self.timeline = self._crop(timelines)
        self.title_box, self.title = None, None
        if s.title:
            img, draw = canvas()
            y = margin + round(0.085 * size * 1.12)
            draw.text((margin + 3, y), s.title, font=_font(round(0.026 * size), False),
                      fill=(200, 210, 225, 255))
            self.title_box, title = self._crop({0: img})
            self.title = title[0]

    @staticmethod
    def _crop(images: dict[int, Image.Image]):
        boxes = [im.getbbox() for im in images.values() if im.getbbox()]
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        out = {}
        for k, im in images.items():
            arr = np.asarray(im.crop((x0, y0, x1, y1)), dtype=np.float32)
            alpha = arr[..., 3:4] / 255.0
            out[k] = np.concatenate([arr[..., :3] * alpha, alpha], axis=-1)
        return (slice(y0, y1), slice(x0, x1)), out

    @staticmethod
    def _over(frame: np.ndarray, box, layer: np.ndarray) -> None:
        region = frame[box]
        region *= 1.0 - layer[..., 3:4]
        region += layer[..., :3]

    def composite(self, frame: np.ndarray, st: FrameState) -> None:
        """Draw labels for ``st`` onto ``frame`` (float32 HxWx3) in place."""
        if self.title is not None:
            self._over(frame, self.title_box, self.title)
        if not st.in_transition:
            self._over(frame, self.year_box, self.year[st.from_idx])
            self._over(frame, self.timeline_box, self.timeline[st.from_idx])
            return
        fade_out, fade_in = year_label_alphas(st.blend)
        self._over(frame, self.year_box,
                   fade_out * self.year[st.from_idx] + fade_in * self.year[st.to_idx])
        tl_from = self.timeline[st.from_idx]
        self._over(frame, self.timeline_box, tl_from + st.blend * (self.timeline[st.to_idx] - tl_from))


def year_label_alphas(blend: float) -> tuple[float, float]:
    """Opacity of (old, new) year label: old fades out, then new fades in.

    Overlaying both numbers would show ghosted digits, so the swap happens at
    ``blend == 0.5`` with neither label overlapping the other.
    """
    return max(0.0, 1.0 - 2.0 * blend), max(0.0, 2.0 * blend - 1.0)


# ---------------------------------------------------------------------------
# Simplified Sentinel-2 3-D model
# ---------------------------------------------------------------------------
# Body frame (metres): a = along-track (velocity), c = cross-track (solar wing),
# n = nadir (towards Earth).  A face is (vertices, normal, rgb 0..1, ks, shininess);
# a part is (name, front faces, back faces).  ``back is None`` marks a closed
# part whose faces are culled individually; otherwise it is a two-sided panel.

BUS_SIZE = (2.0, 1.7, 2.6)
WING_YOKE = 0.9
WING_PANEL = (1.9, 1.5)   # length along the wing, width
WING_GAP = 0.08
WING_PANELS = 3
WING_HEIGHT = -0.35       # nadir coordinate of the wing axis
SENTINEL2_SPAN = BUS_SIZE[1] + WING_YOKE + WING_PANELS * WING_PANEL[0] + (WING_PANELS - 1) * WING_GAP

GOLD_FOIL = (0.86, 0.63, 0.22)
SILVER = (0.80, 0.82, 0.85)
INSTRUMENT_WHITE = (0.90, 0.91, 0.93)
SOLAR_CELL = (0.08, 0.16, 0.42)
PANEL_FRAME = (0.62, 0.65, 0.70)
PANEL_BACK = (0.74, 0.74, 0.71)


def _quad(centre, axis: int, sign: float, size_uv, colour, ks=0.0, shininess=1.0,
          cells=(1, 1), jitter=0.0, rng=None):
    """Axis-aligned rectangle on the ``axis`` = const plane, optionally tiled."""
    u, v = (axis + 1) % 3, (axis + 2) % 3
    normal = np.zeros(3)
    normal[axis] = sign
    centre = np.asarray(centre, float)
    faces = []
    for i in range(cells[0]):
        for j in range(cells[1]):
            corners = []
            for cu, cv in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)):
                p = centre.copy()
                p[u] += (cu / cells[0] - 0.5) * size_uv[0]
                p[v] += (cv / cells[1] - 0.5) * size_uv[1]
                corners.append(p)
            shade = 1.0 + jitter * rng.uniform(-1.0, 1.0) if jitter else 1.0
            faces.append((np.array(corners), normal, np.asarray(colour) * shade, ks, shininess))
    return faces


def _box(centre, size, colour, ks=0.0, shininess=1.0, cells=(1, 1), jitter=0.0, rng=None):
    centre, half = np.asarray(centre, float), np.asarray(size, float) / 2
    faces = []
    for axis in range(3):
        u, v = (axis + 1) % 3, (axis + 2) % 3
        for sign in (-1.0, 1.0):
            face_centre = centre.copy()
            face_centre[axis] += sign * half[axis]
            faces += _quad(face_centre, axis, sign, (2 * half[u], 2 * half[v]), colour,
                           ks, shininess, cells, jitter, rng)
    return faces


def sentinel2_static_parts() -> list:
    """Bus with gold foil, nadir-pointing MSI instrument, radiator, star trackers, yoke."""
    rng = np.random.default_rng(2)
    a, c, n = BUS_SIZE
    # Foil crinkle: tiles of slightly different brightness.
    bus = _box((0, 0, 0), BUS_SIZE, GOLD_FOIL, 0.45, 10, (2, 4), 0.08, rng)
    bus += _quad((0.0, -c / 2 - 0.01, -0.15), 1, -1.0, (1.7, 1.5), INSTRUMENT_WHITE, 0.3, 20)
    msi_centre = (0.15, 0.0, n / 2 + 0.45)
    msi = _box(msi_centre, (1.4, 1.3, 0.9), INSTRUMENT_WHITE, 0.3, 16)
    msi += _quad((0.15, 0.0, n / 2 + 0.91), 2, 1.0, (0.75, 0.6), (0.04, 0.05, 0.08), 0.6, 40)
    trackers = _box((-0.45, -0.45, -n / 2 - 0.2), (0.45, 0.45, 0.4), (0.30, 0.32, 0.36), 0.4, 20)
    yoke = _box((0.0, c / 2 + WING_YOKE / 2, WING_HEIGHT), (0.12, WING_YOKE, 0.12), SILVER, 0.5, 20)
    return [("bus", bus, None), ("msi", msi, None), ("trackers", trackers, None),
            ("yoke", yoke, None)]


def sentinel2_wing(facing_body: np.ndarray) -> list:
    """Solar wing panels, turned about the wing axis to face ``facing_body``."""
    normal = np.array([facing_body[0], 0.0, facing_body[2]])
    if np.linalg.norm(normal) < 1e-6:
        normal = np.array([0.0, 0.0, -1.0])
    normal /= np.linalg.norm(normal)
    along = np.array([0.0, 1.0, 0.0])
    across = np.cross(along, normal)
    length, width = WING_PANEL

    def rect(centre, half_l, half_w, colour, face_normal, ks, shininess):
        corners = np.array([centre + sl * half_l * along + sw * half_w * across
                            for sl, sw in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
        return (corners, face_normal, np.asarray(colour), ks, shininess)

    parts = []
    for k in range(WING_PANELS):
        start = BUS_SIZE[1] / 2 + WING_YOKE + k * (length + WING_GAP)
        centre = np.array([0.0, start + length / 2, WING_HEIGHT])
        front = [rect(centre, length / 2, width / 2, PANEL_FRAME, normal, 0.4, 20)]
        cell_l, cell_w, border = length / 3, width / 2, 0.05
        for i in range(3):
            for j in range(2):
                cell_centre = (centre + ((i + 0.5) * cell_l - length / 2) * along
                               + ((j + 0.5) * cell_w - width / 2) * across)
                front.append(rect(cell_centre, cell_l / 2 - border, cell_w / 2 - border,
                                  SOLAR_CELL, normal, 0.7, 45))
        back = [rect(centre, length / 2, width / 2, PANEL_BACK, -normal, 0.2, 10)]
        parts.append((f"panel{k}", front, back))
    return parts


class SatelliteLayers:
    """Stylised Sentinel-2A/B: circular orbits, enlarged 3-D models, surface swaths.

    Orbit altitude/inclination and swath width are nominal mission values.
    Motion is deliberately slowed; this is not an ephemeris or coverage model.
    """

    EARTH_KM = 6371.0
    ORBIT_RADIUS = 1.0 + 786.0 / EARTH_KM
    SWATH_HALF_ANGLE = 290.0 / (2.0 * EARTH_KM)

    def __init__(self, s: RenderSettings):
        if not math.isfinite(s.orbits_per_turn) or s.orbits_per_turn <= 0:
            raise ValueError("orbits_per_turn must be finite and > 0")
        if not math.isfinite(s.swath_trail_s) or s.swath_trail_s <= 0:
            raise ValueError("swath_trail_s must be finite and > 0")
        if s.satellite_size_px < 8:
            raise ValueError("satellite_size_px must be >= 8")
        self.s = s
        self.tilt = globe_matrix(180.0, s.tilt_deg, 0.0)[:3, :3]
        # The unlit disc implies the Sun sits behind the camera (+x = local noon,
        # east = +y).  Sentinel-2 crosses the equator southbound at 10:30 LTDN,
        # i.e. 22.5° west of noon, so the ascending node (u) lies 180° from that.
        ltdn_h, inc = 10.5, math.radians(98.62)
        node = math.radians((ltdn_h - 12.0) * 15.0 + 180.0)
        self.u = np.array([math.cos(node), math.sin(node), 0.0])
        self.v = np.array([
            -math.sin(node) * math.cos(inc),
            math.cos(node) * math.cos(inc),
            math.sin(inc),
        ])
        self.normal = np.cross(self.u, self.v)
        self.focal = s.window_size / (2 * math.tan(math.radians(VIEW_ANGLE_DEG / 2)))
        self.eye = np.array([s.camera_distance, 0.0, 0.0])
        # Key light from the viewer's upper left; unrelated to the unlit globe.
        self.light = np.array([0.6, -0.55, 0.6]) / np.linalg.norm([0.6, -0.55, 0.6])
        # Globe units per model metre so the full span appears satellite_size_px long.
        self.scale = s.satellite_size_px * s.camera_distance / (self.focal * SENTINEL2_SPAN)
        self.static_parts = sentinel2_static_parts()

    def directions(self, angles_deg: np.ndarray) -> np.ndarray:
        angles = np.radians(angles_deg)
        return np.cos(angles)[..., None] * self.u + np.sin(angles)[..., None] * self.v

    def positions(self, angle_deg: float) -> np.ndarray:
        phase = angle_deg * self.s.orbits_per_turn
        return self.ORBIT_RADIUS * self.directions(np.array([phase, phase + 180])) @ self.tilt.T

    def project(self, points: np.ndarray) -> np.ndarray:
        scale = self.focal / (self.s.camera_distance - points[..., 0])
        centre = (self.s.window_size - 1) / 2
        return np.stack((centre + points[..., 1] * scale,
                         centre - points[..., 2] * scale), axis=-1)

    def ground_track(self, angle_deg: float, phase: float) -> np.ndarray:
        """Return both swath edges, oldest first, carried along by Earth spin."""
        span = 360.0 * self.s.swath_trail_s / self.s.rotation_s
        count = max(2, math.ceil(span * (1 + self.s.orbits_per_turn)) + 1)
        ages = np.linspace(span, 0.0, count)
        track = self.directions((angle_deg - ages) * self.s.orbits_per_turn + phase)
        edges = (math.cos(self.SWATH_HALF_ANGLE) * track[:, None, :]
                 + math.sin(self.SWATH_HALF_ANGLE)
                 * np.array([-1, 1])[None, :, None] * self.normal)
        spin = np.radians(ages)
        x, y = edges[..., 0].copy(), edges[..., 1].copy()
        edges[..., 0] = np.cos(spin)[:, None] * x - np.sin(spin)[:, None] * y
        edges[..., 1] = np.sin(spin)[:, None] * x + np.cos(spin)[:, None] * y
        return edges @ self.tilt.T

    def clip_surface(self, polygon: np.ndarray) -> np.ndarray:
        """Clip a small surface polygon to the perspective-visible hemisphere."""
        horizon = 1.0 / self.s.camera_distance
        result = []
        previous = polygon[-1]
        for point in polygon:
            inside, was_inside = point[0] >= horizon, previous[0] >= horizon
            if inside != was_inside:
                fraction = (horizon - previous[0]) / (point[0] - previous[0])
                result.append(previous + fraction * (point - previous))
            if inside:
                result.append(point)
            previous = point
        return np.asarray(result).reshape(-1, 3)

    @staticmethod
    def composite_image(frame: np.ndarray, image: Image.Image, coverage: np.ndarray) -> None:
        box = image.getbbox()
        if box is None:
            return
        x0, y0, x1, y1 = box
        region = frame[y0:y1, x0:x1]
        rgba = np.asarray(image.crop(box), dtype=np.float32)
        alpha = rgba[..., 3:4] / 255.0 * coverage[y0:y1, x0:x1, None]
        region *= 1.0 - alpha
        region += rgba[..., :3] * alpha

    def composite_swaths(self, frame: np.ndarray, angle_deg: float, mask: np.ndarray) -> None:
        if not self.s.show_swath:
            return
        size = self.s.window_size
        layer = Image.new("RGBA", (size * 2, size * 2))
        draw = ImageDraw.Draw(layer)
        for phase in (0.0, 180.0):
            edges = self.ground_track(angle_deg, phase)
            for j in range(len(edges) - 1):
                polygon = self.clip_surface(edges[[j, j, j + 1, j + 1], [0, 1, 1, 0]])
                if len(polygon) < 3:
                    continue
                xy = self.project(polygon) * 2
                alpha = round(95 * (j + 0.5) / (len(edges) - 1))
                draw.polygon([tuple(p) for p in xy], fill=(90, 225, 245, alpha))
        layer = layer.resize((size, size), Image.Resampling.LANCZOS)
        self.composite_image(frame, layer, mask)

    def satellite_models(self, angle_deg: float) -> list[list]:
        """Per satellite: parts transformed to globe/camera coordinates.

        Body axes follow the orbit: along-track velocity, wing across track,
        instrument towards Earth's centre.
        """
        phase = angle_deg * self.s.orbits_per_turn
        velocities = self.directions(np.array([phase + 90.0, phase + 270.0])) @ self.tilt.T
        models = []
        for position, forward in zip(self.positions(angle_deg), velocities):
            nadir = -position / np.linalg.norm(position)
            basis = np.stack([forward, np.cross(nadir, forward), nadir])
            # Stylised: the wing favours the viewer so its cells never go edge-on.
            facing = self.light + 1.5 * (self.eye - position) / np.linalg.norm(self.eye - position)
            parts = self.static_parts + sentinel2_wing(basis @ facing)

            def to_world(faces):
                return [(position + self.scale * verts @ basis, normal @ basis, colour, ks, sh)
                        for verts, normal, colour, ks, sh in faces]

            models.append([(name, to_world(front), None if back is None else to_world(back))
                           for name, front, back in parts])
        return models

    def _shade(self, centroid, normal, colour, ks, shininess) -> tuple[int, int, int]:
        view = self.eye - centroid
        view /= np.linalg.norm(view)
        diffuse = max(0.0, float(normal @ self.light))
        half = self.light + view
        spec = ks * max(0.0, float(normal @ half) / np.linalg.norm(half)) ** shininess
        rgb = 255.0 * (colour * (0.22 + 0.9 * diffuse) + spec)
        return tuple(int(x) for x in np.clip(rgb, 0, 255))

    def composite_satellites(self, frame: np.ndarray, angle_deg: float, mask: np.ndarray) -> None:
        """Rasterise the 3-D models (painter's algorithm, 4x supersampled) onto ``frame``.

        Geometry in front of the horizon plane x = 1/D can never be hidden by
        Earth; geometry behind it is hidden exactly where it overlaps the disc.
        """
        ss = 4
        half = math.ceil(0.75 * self.s.satellite_size_px) + 4
        horizon = 1.0 / self.s.camera_distance
        for position, model in zip(self.positions(angle_deg), self.satellite_models(angle_deg)):
            cx, cy = (round(v) for v in self.project(position))
            x0, y0 = cx - half, cy - half
            layers = [Image.new("RGBA", (2 * half * ss,) * 2) for _ in range(2)]
            draws = [ImageDraw.Draw(layer) for layer in layers]

            def centroid(faces):
                return np.mean([verts.mean(axis=0) for verts, *_ in faces], axis=0)

            order = sorted(model, key=lambda part: -np.linalg.norm(self.eye - centroid(part[1])))
            for _, front, back in order:
                centre = centroid(front)
                if back is None:
                    faces = [f for f in front if f[1] @ (self.eye - f[0].mean(axis=0)) > 0]
                else:
                    faces = front if front[0][1] @ (self.eye - centre) > 0 else back
                draw = draws[int(centre[0] < horizon)]
                for verts, normal, colour, ks, shininess in faces:
                    fill = self._shade(verts.mean(axis=0), normal, colour, ks, shininess) + (255,)
                    xy = (self.project(verts) + 0.5 - (x0, y0)) * ss
                    draw.polygon([tuple(p) for p in xy], fill=fill, outline=fill)
            for behind, layer in enumerate(layers):
                rgba = np.asarray(layer, dtype=np.float32)
                rgba[..., :3] *= rgba[..., 3:4] / 255.0
                rgba = rgba.reshape(2 * half, ss, 2 * half, ss, 4).mean(axis=(1, 3))
                self._composite_premultiplied(frame, rgba, x0, y0, (1.0 - mask) if behind else None)

    @staticmethod
    def _composite_premultiplied(frame, rgba, x0, y0, coverage=None) -> None:
        h, w = rgba.shape[:2]
        fx0, fy0 = max(x0, 0), max(y0, 0)
        fx1, fy1 = min(x0 + w, frame.shape[1]), min(y0 + h, frame.shape[0])
        if fx0 >= fx1 or fy0 >= fy1:
            return
        crop = rgba[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0]
        weight = 1.0 if coverage is None else coverage[fy0:fy1, fx0:fx1, None]
        region = frame[fy0:fy1, fx0:fx1]
        region *= 1.0 - crop[..., 3:4] / 255.0 * weight
        region += crop[..., :3] * weight


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render(s: RenderSettings, only_transition: bool = False) -> Path:
    n = len(s.years)
    fpr, fpy = s.frames_per_rotation, s.frames_per_year
    schedule = frame_schedule(n, fpy, s.crossfade_frames, s.loop, fpr)
    total_turns = n * fpy / fpr
    if s.loop and abs(total_turns - round(total_turns)) > 1e-9:
        print(f"  warning: loop = true but {total_turns:g} turns is not whole -> "
              "orientation jumps when the video restarts")
    satellites = SatelliteLayers(s) if s.satellites else None
    if satellites is not None:
        if s.camera_distance <= satellites.ORBIT_RADIUS:
            raise ValueError("camera_distance must exceed the satellite orbit radius")
        orbit_turns = total_turns * s.orbits_per_turn
        if s.loop and abs(orbit_turns - round(orbit_turns)) > 1e-9:
            print(f"  warning: loop = true but {orbit_turns:g} satellite orbits is not whole -> "
                  "satellites and swaths jump when the video restarts")
    if only_transition:
        if n < 2:
            raise ValueError("--only-transition needs at least two years")
        schedule = [schedule[i] for i in transition_preview_range(fpy, fpr) if i < len(schedule)]

    needed = sorted({st.from_idx for st in schedule} | {st.to_idx for st in schedule})
    missing = [str(s.input_path(s.years[k])) for k in needed if not s.input_path(s.years[k]).exists()]
    if missing:
        raise FileNotFoundError("Missing input image(s):\n  " + "\n  ".join(missing))

    textures = {}
    for k in needed:
        print(f"  loading {s.years[k]}: {s.input_path(s.years[k]).name}")
        textures[k] = load_texture(s.input_path(s.years[k]))

    size = s.window_size
    radius = globe_radius_px(size, s.camera_distance)
    mask, limb, r = disc_layers(size, radius, s.limb_darkening)
    background = make_background(s, r, radius) * (1.0 - mask)[..., None]
    limb3 = limb[..., None]
    labels = LabelLayers(s, needed) if s.show_labels else None

    plotter = pv.Plotter(off_screen=True, window_size=[size, size])
    plotter.set_background("black")  # globe edge AA blends to black → premultiplied
    plotter.enable_anti_aliasing("ssaa")
    sphere = make_textured_sphere(s.sphere_resolution * 2, s.sphere_resolution)
    actor = plotter.add_mesh(sphere, texture=textures[needed[0]], lighting=False)
    current_tex = needed[0]
    plotter.camera.position = (s.camera_distance, 0.0, 0.0)
    plotter.camera.focal_point = (0.0, 0.0, 0.0)
    plotter.camera.up = (0.0, 0.0, 1.0)
    plotter.camera.view_angle = VIEW_ANGLE_DEG

    def shot(tex_idx: int) -> np.ndarray:
        nonlocal current_tex
        if tex_idx != current_tex:
            actor.texture = textures[tex_idx]
            current_tex = tex_idx
        # screenshot() only renders on first use; model-matrix changes need an explicit render.
        plotter.render()
        return plotter.screenshot(return_img=True).astype(np.float32)

    out = Path(s.output)
    if only_transition:
        out = out.with_name(f"{out.stem}_transition{out.suffix}")
    out.parent.mkdir(parents=True, exist_ok=True)
    gif_path = out.with_suffix(".gif")
    print(
        f"Rendering {len(schedule)} frames ({len(schedule) / s.fps:.1f}s @ {s.fps} fps, "
        f"{size}x{size}, globe radius {radius:.0f}px) -> {out}"
    )

    mp4_w = imageio.get_writer(
        str(out), fps=s.fps, codec="libx264", quality=None, macro_block_size=8,
        ffmpeg_params=["-crf", str(s.crf), "-movflags", "+faststart"],
    )
    gif_w = imageio.get_writer(str(gif_path), mode="I", duration=2000 / s.fps, loop=0) if s.gif else None
    t0 = time.perf_counter()
    try:
        for k, st in enumerate(schedule):
            actor.user_matrix = globe_matrix(st.angle_deg, s.tilt_deg, s.start_lon)
            globe = shot(st.from_idx)
            if st.in_transition:
                nxt = shot(st.to_idx)
                nxt -= globe
                nxt *= st.blend
                globe += nxt
            if satellites is not None:
                satellites.composite_swaths(globe, st.angle_deg, mask)
            globe *= limb3
            globe += background
            if satellites is not None:
                satellites.composite_satellites(globe, st.angle_deg, mask)
            if labels is not None:
                labels.composite(globe, st)
            globe += 0.5
            frame = np.clip(globe, 0, 255, out=globe).astype(np.uint8)
            mp4_w.append_data(frame)
            if gif_w is not None and k % 2 == 0:
                gif_w.append_data(frame[::2, ::2])
            if (k + 1) % (s.fps * 5) == 0 or k + 1 == len(schedule):
                el = time.perf_counter() - t0
                eta = el / (k + 1) * (len(schedule) - k - 1)
                print(f"  frame {k + 1}/{len(schedule)}  ({el:.0f}s elapsed, ~{eta:.0f}s left)")
    finally:
        mp4_w.close()
        if gif_w is not None:
            gif_w.close()
        for tex in textures.values():
            tex.ReleaseGraphicsResources(plotter.render_window)
        plotter.close()

    print(f"Done -- saved {out}" + (f" and {gif_path}" if s.gif else ""))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help=f"TOML config (default: {DEFAULT_CONFIG})")
    parser.add_argument("--name", help="Only render the [[render]] entry with this name")
    parser.add_argument("--only-transition", action="store_true",
                        help="Render one 360° turn centred on the first year change "
                             "(writes <output>_transition.mp4)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    entries = cfg.get("render", [{}])
    if args.name:
        entries = [e for e in entries if e.get("name") == args.name]
        if not entries:
            parser.error(f"no [[render]] entry named {args.name!r} in {args.config}")
    for entry in entries:
        settings = RenderSettings.from_config(cfg.get("global", {}), entry)
        print(f"== {settings.name} ==")
        render(settings, only_transition=args.only_transition)


if __name__ == "__main__":
    main()
