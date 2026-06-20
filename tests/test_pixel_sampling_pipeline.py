from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from nanoleaf_sync.capture.kmsgrab import KMSGrabCapture
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.presets import effective_sampling_mode
from nanoleaf_sync.runtime.content_bounds import detect_content_bounds
from nanoleaf_sync.runtime.processing import scale_zones_to_display
from nanoleaf_sync.runtime.zone_presets import apply_layout_transform, make_edge_weighted_zones
from nanoleaf_sync.runtime.zones import zone_colors_array


def test_effective_sampling_mode_defaults_to_edge_direct_for_reference() -> None:
    assert (
        effective_sampling_mode(
            sampling_mode="auto",
            color_style="reference",
            accuracy_mode=False,
        )
        == "edge_direct"
    )


def test_effective_sampling_mode_ambient_uses_vivid_weighted() -> None:
    assert (
        effective_sampling_mode(
            sampling_mode="auto",
            color_style="ambient",
            accuracy_mode=False,
        )
        == "vivid_weighted"
    )


def test_peak_luma_prefers_bright_edge_pixels() -> None:
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[:4, :, :] = np.array([255, 255, 255], dtype=np.uint8)
    frame[4:, :, :] = np.array([20, 20, 20], dtype=np.uint8)
    zones_px = [(0, 0, 100, 20)]
    peak = zone_colors_array(frame, zones_px, sampling_mode="peak_luma")
    area_average = zone_colors_array(frame, zones_px, sampling_mode="area_average")
    assert float(np.mean(peak[0])) > float(np.mean(area_average[0]))


def test_letterbox_detection_clips_top_and_bottom_zones() -> None:
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    frame[40:160, :, :] = np.array([0, 0, 255], dtype=np.uint8)
    bounds = detect_content_bounds(frame)
    assert bounds[1] >= 35
    assert bounds[3] <= 165
    from nanoleaf_sync.runtime.content_bounds import letterbox_margins_significant

    assert letterbox_margins_significant(frame, bounds)


def test_layout_transform_shrinks_toward_center() -> None:
    zones = make_edge_weighted_zones(12, width=320, height=180, edge_locality="balanced")
    transformed = apply_layout_transform(zones, inset=0.05, scale=0.85)
    assert transformed[0].y > zones[0].y
    assert transformed[0].h <= zones[0].h


def test_scale_zones_to_display_scales_coordinates() -> None:
    scaled = scale_zones_to_display(
        [(10, 20, 30, 40)],
        capture_width=480,
        capture_height=270,
        display_width=1920,
        display_height=1080,
    )
    assert scaled[0][0] == 40
    assert scaled[0][1] == 80


def test_kmsgrab_skips_drm_patch_path_by_default(monkeypatch) -> None:
    capture = KMSGrabCapture(width=480, height=270, allow_fallback=False)
    sampler = MagicMock()
    sampler.capture_zone_rects.side_effect = AssertionError(
        "DRM patch capture should not run when disabled"
    )
    capture._drm_zone_sampler = sampler
    capture._drm_capture_impl = lambda **kwargs: np.zeros((270, 480, 3), dtype=np.uint8)
    out = capture.capture(zone_rects=[(0, 0, 20, 20)])
    assert out.shape == (270, 480, 3)
    sampler.capture_zone_rects.assert_not_called()


def test_resolve_capture_dims_grows_with_zone_count() -> None:
    from nanoleaf_sync.capture.dimensions import resolve_capture_dims

    low = resolve_capture_dims(AppConfig(device_zone_count=8))
    high = resolve_capture_dims(AppConfig(device_zone_count=80))
    assert high[0] >= low[0]
