from __future__ import annotations

from nanoleaf_sync.runtime.processing import apply_brightness, ema_smooth


def test_apply_brightness_scales_colors() -> None:
    colors = [(100, 120, 140), (10, 20, 30)]
    out = apply_brightness(colors, 0.5)
    assert out == [(50, 60, 70), (5, 10, 15)]


def test_ema_smooth_matches_expected_rounding() -> None:
    prev = [(10, 20, 30), (100, 110, 120)]
    current = [(30, 60, 90), (200, 220, 240)]
    out = ema_smooth(prev, current, alpha=0.25)
    assert out == [(15, 30, 45), (125, 138, 150)]
