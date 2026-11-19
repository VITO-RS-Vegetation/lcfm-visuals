"""Tests for the pure-Python helpers in scripts/rotating_globe.py."""

from __future__ import annotations

import pytest
import numpy as np

from rotating_globe import (
    RenderSettings,
    SatelliteLayers,
    disc_layers,
    frame_schedule,
    globe_matrix,
    globe_radius_px,
    transition_preview_range,
    year_label_alphas,
)

N_YEARS, FPR, CF = 5, 450, 30  # 15 s/turn and 1 s crossfade at 30 fps


def _transitions(states):
    return [st for st in states if st.in_transition]


def test_one_rotation_per_year():
    states = frame_schedule(N_YEARS, FPR, CF)
    assert len(states) == N_YEARS * FPR
    assert states[FPR].angle_deg == pytest.approx(360.0)
    # Last frame is one step short of the starting orientation → seamless loop.
    assert states[-1].angle_deg + 360.0 / FPR == pytest.approx(360.0 * N_YEARS)


def test_crossfade_is_centred_on_year_boundary():
    states = frame_schedule(N_YEARS, FPR, CF)
    fade = [st for st in _transitions(states) if (st.from_idx, st.to_idx) == (0, 1)]
    assert [st.index for st in fade] == list(range(FPR - CF // 2, FPR + CF // 2))
    blends = [st.blend for st in fade]
    assert blends == sorted(blends)
    assert all(0.0 < b < 1.0 for b in blends)
    for a, b in zip(blends, reversed(blends)):
        assert a + b == pytest.approx(1.0)
    # Mid-rotation frames show a single year.
    assert states[FPR + FPR // 2].from_idx == states[FPR + FPR // 2].to_idx == 1


def test_loop_fades_last_year_into_first():
    states = frame_schedule(N_YEARS, FPR, CF, loop=True)
    for st in (states[0], states[-1]):
        assert (st.from_idx, st.to_idx) == (N_YEARS - 1, 0)
    assert len(_transitions(states)) == N_YEARS * CF


def test_no_loop_starts_and_ends_on_pure_years():
    states = frame_schedule(N_YEARS, FPR, CF, loop=False)
    assert (states[0].from_idx, states[0].blend) == (0, 0.0)
    assert (states[-1].from_idx, states[-1].blend) == (N_YEARS - 1, 0.0)
    assert len(_transitions(states)) == (N_YEARS - 1) * CF


def test_zero_crossfade_is_hard_cut():
    states = frame_schedule(N_YEARS, FPR, 0)
    assert not _transitions(states)
    assert (states[FPR - 1].from_idx, states[FPR].from_idx) == (0, 1)


def test_single_year_never_transitions():
    assert not _transitions(frame_schedule(1, FPR, CF))


def test_crossfade_longer_than_rotation_rejected():
    with pytest.raises(ValueError):
        frame_schedule(N_YEARS, FPR, FPR + 1)


def test_preview_is_one_turn_containing_first_year_change():
    states = frame_schedule(N_YEARS, FPR, CF)
    preview = [states[i] for i in transition_preview_range(FPR)]
    assert len(preview) == FPR
    pairs = {(st.from_idx, st.to_idx) for st in _transitions(preview)}
    assert pairs == {(0, 1)}
    assert len(_transitions(preview)) == CF


@pytest.mark.parametrize(("turns_per_year", "loop"), [(0.5, False), (0.6, True)])
def test_years_decoupled_from_rotation(turns_per_year, loop):
    fpy = round(turns_per_year * FPR)
    states = frame_schedule(N_YEARS, fpy, CF, loop=loop, frames_per_rotation=FPR)
    assert len(states) == N_YEARS * fpy
    assert states[-1].angle_deg + 360.0 / FPR == pytest.approx(360.0 * N_YEARS * turns_per_year)
    first_change = [st.index for st in _transitions(states) if (st.from_idx, st.to_idx) == (0, 1)]
    assert first_change == list(range(fpy - CF // 2, fpy + CF // 2))
    assert states[-1].to_idx == (0 if loop else N_YEARS - 1)


@pytest.mark.parametrize("blend", [0.0, 0.2, 0.5, 0.8, 1.0])
def test_year_labels_never_overlap(blend):
    old, new = year_label_alphas(blend)
    assert old == 0.0 or new == 0.0


def test_settings_merge_and_reject_unknown_keys():
    s = RenderSettings.from_config({"fps": 25, "years": [2020, 2021]}, {"fps": 50})
    assert (s.fps, s.years, s.frames_per_rotation) == (50, [2020, 2021], 750)
    with pytest.raises(ValueError, match="rotaton_s"):
        RenderSettings.from_config({}, {"rotaton_s": 10})


def test_satellite_phasing_altitude_and_loop():
    satellites = SatelliteLayers(RenderSettings())
    for angle in (0.0, 43.0, 180.0):
        positions = satellites.positions(angle)
        np.testing.assert_allclose(positions[0], -positions[1], atol=1e-14)
        np.testing.assert_allclose(np.linalg.norm(positions, axis=1), 1 + 786 / 6371)
        np.testing.assert_allclose(positions, satellites.positions(angle + 720), atol=1e-14)
        np.testing.assert_allclose(
            satellites.ground_track(angle, 0),
            satellites.ground_track(angle + 720, 0), atol=1e-14,
        )


def test_swath_is_on_surface_and_ends_under_satellite():
    satellites = SatelliteLayers(RenderSettings())
    track = satellites.ground_track(32.0, 0.0)
    np.testing.assert_allclose(np.linalg.norm(track, axis=-1), 1)
    centre = track[-1].mean(axis=0)
    np.testing.assert_allclose(
        centre / np.linalg.norm(centre),
        satellites.positions(32.0)[0] / satellites.ORBIT_RADIUS,
    )
    angular_width = np.arccos(np.dot(track[-1, 0], track[-1, 1]))
    assert angular_width * satellites.EARTH_KM == pytest.approx(290)


def test_old_swath_rotates_with_earth_after_acquisition():
    s = RenderSettings()
    satellites = SatelliteLayers(s)
    span = 360 * s.swath_trail_s / s.rotation_s
    acquired = satellites.ground_track(24, 0)[-1]
    later = satellites.ground_track(24 + span, 0)[0]
    rotation = (globe_matrix(180 + span, s.tilt_deg, 0)[:3, :3]
                @ satellites.tilt.T)
    np.testing.assert_allclose(later, acquired @ rotation.T, atol=1e-14)


def test_satellite_projection_and_surface_horizon_clipping():
    s = RenderSettings(window_size=200)
    satellites = SatelliteLayers(s)
    horizon = 1 / s.camera_distance
    edge = np.array([[horizon, np.sqrt(1 - horizon**2), 0]])
    assert satellites.project(edge)[0, 0] == pytest.approx(
        99.5 + globe_radius_px(s.window_size, s.camera_distance)
    )
    hidden = np.array([[-1, 0, 0], [-0.9, 0.1, 0], [-0.9, 0, 0.1]])
    assert len(satellites.clip_surface(hidden)) == 0
    crossing = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    clipped = satellites.clip_surface(crossing)
    assert len(clipped) == 3
    assert np.all(clipped[:, 0] >= horizon - 1e-14)


def test_back_satellite_is_hidden_and_front_satellite_covers_background():
    s = RenderSettings(window_size=200, satellite_size_px=16)
    satellites = SatelliteLayers(s)
    mask, _, _ = disc_layers(200, globe_radius_px(200, s.camera_distance), 0.25)
    frame = np.full((200, 200, 3), 100.0, dtype=np.float32)
    satellites.composite_satellites(frame, 0, mask)
    back, front = np.rint(satellites.project(satellites.positions(0))).astype(int)
    np.testing.assert_array_equal(frame[back[1], back[0]], 100)
    assert not np.array_equal(frame[front[1], front[0]], [100, 100, 100])
    assert frame.max() <= 255


def test_swath_toggle_occlusion_and_rendered_loop():
    s = RenderSettings(window_size=160, satellite_size_px=16)
    satellites = SatelliteLayers(s)
    mask, _, _ = disc_layers(160, globe_radius_px(160, s.camera_distance), 0.25)
    frames = []
    for angle in (45.0, 765.0):
        frame = np.zeros((160, 160, 3), dtype=np.float32)
        satellites.composite_swaths(frame, angle, mask)
        assert frame.sum() > 0
        assert not frame[mask == 0].any()
        satellites.composite_satellites(frame, angle, mask)
        frames.append(frame)
    np.testing.assert_allclose(frames[0], frames[1])
    s.show_swath = False
    frame = np.zeros_like(frames[0])
    satellites.composite_swaths(frame, 45, mask)
    assert not frame.any()


def test_satellite_model_points_instrument_at_earth_and_matches_size():
    s = RenderSettings(window_size=600, satellite_size_px=60)
    satellites = SatelliteLayers(s)
    for model in satellites.satellite_models(70):
        height = {name: np.linalg.norm(np.concatenate([f[0] for f in front]).mean(axis=0))
                  for name, front, _ in model}
        assert height["msi"] < height["bus"] < height["trackers"]
    mask = np.zeros((600, 600), dtype=np.float32)
    frame = np.zeros((600, 600, 3), dtype=np.float32)
    satellites.composite_satellites(frame, 70, mask)
    for xy in satellites.project(satellites.positions(70)):
        cx, cy = np.rint(xy).astype(int)
        ys, xs = np.nonzero(frame[cy - 60:cy + 60, cx - 60:cx + 60].any(axis=-1))
        extent = np.hypot(np.ptp(xs), np.ptp(ys))
        assert 0.5 * 60 < extent < 1.35 * 60


def test_descending_node_is_at_1030_local_solar_time():
    # Sun behind the camera: +x is local noon, +y is east; 15 degrees per hour.
    satellites = SatelliteLayers(RenderSettings())
    phases = np.arange(0, 360, 0.01)
    track = satellites.directions(phases)
    southbound = np.nonzero((track[:-1, 2] >= 0) & (track[1:, 2] < 0))[0]
    assert len(southbound) == 1
    node = track[southbound[0]]
    local_time = 12 + np.degrees(np.arctan2(node[1], node[0])) / 15
    assert local_time == pytest.approx(10.5, abs=1e-3)


@pytest.mark.parametrize(("key", "value"), [
    ("orbits_per_turn", 0), ("orbits_per_turn", float("nan")),
    ("swath_trail_s", -1), ("satellite_size_px", 0),
])
def test_invalid_satellite_settings_rejected(key, value):
    with pytest.raises(ValueError, match=key):
        SatelliteLayers(RenderSettings(**{key: value}))
