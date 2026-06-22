from __future__ import annotations

import numpy as np

from nanoleaf_sync.config.presets import SYNC_MODE_4D
from nanoleaf_sync.runtime.color_pipeline import ColorPipelineParams, process_zone_colors
from nanoleaf_sync.runtime.zones import (
    _dark_biased_patch_mean,
    detect_zone_patch_mixed_content,
    zone_colors_array,
    zone_colors_array_with_meta,
)


def test_detect_mixed_content_blue_with_pink_icon() -> None:
    patch = np.zeros((40, 60, 3), dtype=np.uint8)
    patch[:, :42, :] = np.array([20, 40, 180], dtype=np.uint8)
    patch[:, 42:, :] = np.array([240, 40, 220], dtype=np.uint8)
    assert detect_zone_patch_mixed_content(patch) is True


def test_detect_mixed_content_uniform_blue_is_not_mixed() -> None:
    patch = np.full((40, 60, 3), np.array([20, 40, 180], dtype=np.uint8), dtype=np.uint8)
    assert detect_zone_patch_mixed_content(patch) is False


def test_vivid_weighted_falls_back_to_area_average_for_mixed_zone() -> None:
    frame = np.zeros((120, 200, 3), dtype=np.uint8)
    frame[:, :140, :] = np.array([20, 40, 180], dtype=np.uint8)
    frame[:, 140:, :] = np.array([240, 40, 220], dtype=np.uint8)
    zones_px = [(0, 80, 200, 40)]
    colors, meta = zone_colors_array_with_meta(
        frame, zones_px, sampling_mode="vivid_weighted", mode="balanced"
    )
    assert meta.per_zone_mixed_fallback[0] is True
    assert meta.per_zone_effective_mode[0] == "area_average"
    area = zone_colors_array(frame, zones_px, sampling_mode="area_average", mode="balanced")
    assert int(np.mean(np.abs(colors.astype(np.int32) - area.astype(np.int32)))) <= 6


def test_overwatch_like_bottom_left_zone_stable_across_icon_toggle() -> None:
    width, height = 320, 200
    zone_rect = (0, 150, 80, 40)
    zones_px = [zone_rect]
    base = np.full((height, width, 3), np.array([20, 40, 180], dtype=np.uint8), dtype=np.uint8)
    with_icon = base.copy()
    with_icon[150:190, 10:70, :] = np.array([240, 40, 220], dtype=np.uint8)
    without_icon = base.copy()
    params = ColorPipelineParams(
        sync_mode=SYNC_MODE_4D,
        color_style="ambient",
        smoothing=0.35,
        motion_preset="responsive",
        return_diagnostics=True,
    )
    prev: list[tuple[float, float, float]] = [(30.0, 50.0, 120.0)]
    sampled_rows: list[np.ndarray] = []
    for frame in (with_icon, with_icon, with_icon, without_icon, without_icon):
        out = process_zone_colors(
            frame=frame,
            precomputed_zone_colors=None,
            prev_smoothed_colors=prev,
            zones_px=zones_px,
            device_zone_indices=[0],
            params=params,
        )
        _colors, sampled, _pre, _final, _timings, _smooth, history = out  # type: ignore[misc]
        sampled_rows.append(np.asarray(sampled[0], dtype=np.int32))
        prev = history
    assert int(abs(sampled_rows[0][2] - sampled_rows[1][2])) <= 5
    assert int(abs(sampled_rows[3][2] - sampled_rows[4][2])) <= 5
    assert int(abs(sampled_rows[0][0] - sampled_rows[1][0])) <= 5
    assert max(r[2] for r in sampled_rows) - min(r[2] for r in sampled_rows) <= 35


def test_konsole_like_top_left_blue_sky_green_text_stable() -> None:
    width, height = 320, 200
    frame = np.full((height, width, 3), np.array([40, 120, 220], dtype=np.uint8), dtype=np.uint8)
    frame[8:36, 8:120, :] = np.array([10, 10, 10], dtype=np.uint8)
    frame[12:32, 12:116, 1] = 220
    zones_px = [(0, 0, 140, 40)]
    colors_a, meta = zone_colors_array_with_meta(
        frame, zones_px, sampling_mode="vivid_weighted", mode="balanced"
    )
    frame_alt = frame.copy()
    frame_alt[12:32, 12:116, 1] = 180
    colors_b, _meta_b = zone_colors_array_with_meta(
        frame_alt, zones_px, sampling_mode="vivid_weighted", mode="balanced"
    )
    assert meta.per_zone_mixed_fallback[0] is True
    delta = np.mean(np.abs(colors_a.astype(np.float32) - colors_b.astype(np.float32)))
    assert float(delta) <= 35.0


def test_low_light_vivid_mode_uses_area_average_per_zone() -> None:
    frame = np.full((80, 120, 3), np.array([24, 25, 23], dtype=np.uint8), dtype=np.uint8)
    frame[10:70, 10:110, 0] = 28
    frame[10:70, 10:110, 2] = 20
    zones_px = [(0, 0, 120, 80)]
    colors, meta = zone_colors_array_with_meta(
        frame, zones_px, sampling_mode="vivid_weighted", mode="balanced"
    )
    assert meta.per_zone_effective_mode[0] == "area_average"
    assert int(np.max(colors[0])) < 32


def test_low_light_dynamic_mode_does_not_pick_vivid_specks() -> None:
    frame = np.full((80, 120, 3), np.array([24, 24, 24], dtype=np.uint8), dtype=np.uint8)
    frame[20:28, 48:56, :] = np.array([39, 4, 38], dtype=np.uint8)
    zones_px = [(0, 0, 120, 80)]
    colors, meta = zone_colors_array_with_meta(
        frame, zones_px, sampling_mode="area_average", mode="dynamic"
    )
    area = zone_colors_array(frame, zones_px, sampling_mode="area_average", mode="balanced")
    assert meta.per_zone_effective_mode[0] == "area_average"
    assert int(np.max(colors[0]) - np.min(colors[0])) <= 3
    assert int(np.mean(np.abs(colors.astype(np.int32) - area.astype(np.int32)))) <= 2


def test_luminance_adaptive_sdr_boost_preserves_bright_highlights() -> None:
    from nanoleaf_sync.runtime.compositor import apply_zone_sdr_boost_float, effective_sdr_boost

    zones = np.asarray([[240.0, 245.0, 250.0], [48.0, 48.0, 48.0]], dtype=np.float32)
    boosted = apply_zone_sdr_boost_float(zones, sdr_boost_nits=203.0, hdr_max_nits=1000.0)
    boost = effective_sdr_boost(sdr_boost_nits=203.0)
    flat_highlight = zones[0] / boost
    flat_grey = zones[1] / boost
    assert float(np.mean(boosted[0])) > float(np.mean(flat_highlight)) + 8.0
    assert abs(float(np.mean(boosted[1])) - float(np.mean(flat_grey))) <= 12.0


def test_dark_biased_mixed_patch_mean_stays_low_chroma() -> None:
    patch = np.zeros((40, 60, 3), dtype=np.uint8)
    patch[:, :52, :] = np.array([4, 4, 4], dtype=np.uint8)
    patch[8:32, 48:58, :] = np.array([240, 40, 220], dtype=np.uint8)
    assert detect_zone_patch_mixed_content(patch) is True
    mean = _dark_biased_patch_mean(patch)
    uniform = np.clip(np.rint(patch.mean(axis=(0, 1))), 0, 255).astype(np.int32)
    assert int(np.max(mean)) < 20
    assert int(np.max(mean)) < int(np.max(uniform))
    mean_lum = 0.2126 * float(mean[0]) + 0.7152 * float(mean[1]) + 0.0722 * float(mean[2])
    uniform_lum = (
        0.2126 * float(uniform[0]) + 0.7152 * float(uniform[1]) + 0.0722 * float(uniform[2])
    )
    assert mean_lum < uniform_lum
