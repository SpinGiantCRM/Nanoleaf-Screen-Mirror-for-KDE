from __future__ import annotations

from nanoleaf_sync.config.normalize import sampling_quality_to_zone_stride
from nanoleaf_sync.runtime.processing import apply_brightness, ema_smooth


def test_apply_brightness_scales_colors() -> None:
    colors = [(100, 120, 140), (10, 20, 30)]
    out = apply_brightness(colors, 0.5)
    assert out == [(71, 86, 101), (5, 11, 19)]


def test_ema_smooth_matches_expected_rounding() -> None:
    prev = [(10, 20, 30), (100, 110, 120)]
    current = [(30, 60, 90), (200, 220, 240)]
    out = ema_smooth(prev, current, alpha=0.25)
    assert out == [(17, 35, 53), (134, 148, 161)]


def test_sampling_quality_presets_map_to_expected_stride() -> None:
    assert sampling_quality_to_zone_stride("low") == 4
    assert sampling_quality_to_zone_stride("balanced") == 2
    assert sampling_quality_to_zone_stride("high") == 1
