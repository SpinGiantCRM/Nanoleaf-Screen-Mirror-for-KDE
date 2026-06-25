from __future__ import annotations

import numpy as np

from nanoleaf_sync.runtime.blending import (
    BlendHysteresisState,
    _hyst_gt,
    _hyst_lt,
    _oklab_blend_rows,
    adaptive_one_euro_blend,
    apply_neighbor_blend,
)


def test_hyst_lt_basic() -> None:
    value = np.array([1.0, 2.0, 3.0])
    assert _hyst_lt(value, enter=2.5, exit=2.0, prev=()).tolist() == [True, True, False]


def test_hyst_gt_basic() -> None:
    value = np.array([1.0, 2.0, 3.0])
    assert _hyst_gt(value, enter=1.5, exit=1.0, prev=()).tolist() == [False, True, True]


def test_scene_activity_transitions() -> None:
    previous = np.full((8, 3), 40.0, dtype=np.float32)
    hyst = BlendHysteresisState()
    for delta in (0.5, 1.0, 4.0, 12.0, 30.0):
        current = previous + delta
        _, diag, hyst = adaptive_one_euro_blend(
            current=current,
            previous=previous,
            smoothing=0.4,
            smoothing_speed=1.0,
            motion_preset="responsive",
            hysteresis=hyst,
        )
        previous = current
    assert diag.scene_activity in {"static", "low", "medium", "high"}


def test_adaptive_one_euro_black_cut() -> None:
    previous = np.zeros((4, 3), dtype=np.float32)
    current = np.full((4, 3), 220.0, dtype=np.float32)
    blended, _, _ = adaptive_one_euro_blend(
        current=current,
        previous=previous,
        smoothing=0.2,
        smoothing_speed=2.0,
        motion_preset="dynamic",
    )
    assert float(np.mean(blended)) > 120.0


def test_adaptive_one_euro_dark_hold() -> None:
    previous = np.full((4, 3), 4.0, dtype=np.float32)
    current = np.full((4, 3), 3.0, dtype=np.float32)
    blended, diag, _ = adaptive_one_euro_blend(
        current=current,
        previous=previous,
        smoothing=0.8,
        smoothing_speed=0.2,
        motion_preset="calm",
    )
    assert float(np.mean(blended)) < 8.0
    assert diag.scene_activity in {"static", "low"}


def test_adaptive_one_euro_large_jump() -> None:
    previous = np.full((6, 3), 10.0, dtype=np.float32)
    current = np.full((6, 3), 240.0, dtype=np.float32)
    blended, _, _ = adaptive_one_euro_blend(
        current=current,
        previous=previous,
        smoothing=0.5,
        smoothing_speed=1.0,
        motion_preset="responsive",
    )
    assert float(np.mean(blended - previous)) > 80.0


def test_adaptive_one_euro_hue_oscillation() -> None:
    previous = np.array([[200.0, 20.0, 20.0], [20.0, 200.0, 20.0]], dtype=np.float32)
    current = np.array([[20.0, 200.0, 20.0], [200.0, 20.0, 20.0]], dtype=np.float32)
    blended, _, _ = adaptive_one_euro_blend(
        current=current,
        previous=previous,
        smoothing=0.35,
        smoothing_speed=1.0,
        motion_preset="responsive",
    )
    assert blended.shape == current.shape


def test_adaptive_one_euro_motion_presets() -> None:
    previous = np.full((6, 3), 50.0, dtype=np.float32)
    current = previous + 25.0
    calm, _, _ = adaptive_one_euro_blend(
        current=current,
        previous=previous,
        smoothing=0.4,
        smoothing_speed=1.0,
        motion_preset="calm",
    )
    dynamic, _, _ = adaptive_one_euro_blend(
        current=current,
        previous=previous,
        smoothing=0.4,
        smoothing_speed=1.0,
        motion_preset="dynamic",
    )
    assert float(np.mean(dynamic - previous)) > float(np.mean(calm - previous))


def test_neighbor_blend_dark_isolation() -> None:
    colors = np.array(
        [
            [0.0, 0.0, 0.0],
            [240.0, 240.0, 240.0],
            [0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    blended = apply_neighbor_blend(colors, spread_mode="balanced")
    assert float(blended[0, 0]) < 20.0


def test_oklab_blend_achromatic_identity() -> None:
    grey = np.full((3, 3), 128.0, dtype=np.float32)
    out = _oklab_blend_rows(grey, grey, np.full(3, 0.5, dtype=np.float32))
    assert np.allclose(out, grey, atol=2.0)


def test_apply_neighbor_blend_stability() -> None:
    colors = np.linspace(20, 220, 12, dtype=np.float32)[:, None] * np.ones((12, 3))
    previous = colors.copy()
    for _ in range(100):
        colors = apply_neighbor_blend(colors, spread_mode="balanced")
        assert np.all(colors >= 0.0)
        assert np.all(colors <= 255.0)
        drift = float(np.max(np.abs(colors - previous)))
        previous = colors.copy()
        assert drift < 80.0
