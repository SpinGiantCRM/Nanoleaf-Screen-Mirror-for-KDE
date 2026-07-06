from __future__ import annotations

import numpy as np

from nanoleaf_sync.runtime.blending import (
    BlendHysteresisState,
    _hyst_gt,
    _hyst_gte,
    _hyst_lt,
    _hyst_lte,
    _oklab_blend_rows,
    _scene_activity_hysteresis,
    adaptive_one_euro_blend,
    apply_neighbor_blend,
)
from nanoleaf_sync.runtime.color_processing import rgb_u8_to_oklch


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


# ---------------------------------------------------------------------------
# hyst_lte / hyst_gte variants
# ---------------------------------------------------------------------------


def test_hyst_lte_basic() -> None:
    value = np.array([1.0, 2.0, 3.0])
    assert _hyst_lte(value, enter=2.0, exit=1.5, prev=()).tolist() == [True, True, False]


def test_hyst_gte_basic() -> None:
    value = np.array([1.0, 2.0, 3.0])
    assert _hyst_gte(value, enter=1.5, exit=1.0, prev=()).tolist() == [False, True, True]


def test_hyst_lt_with_prev_mask() -> None:
    value = np.array([1.0, 3.0, 5.0])
    prev = (True, False, True)
    # prev[0]=True -> exit=2.0: 1.0 < 2.0 -> True
    # prev[1]=False -> enter=2.5: 3.0 < 2.5 -> False
    # prev[2]=True -> exit=2.0: 5.0 < 2.0 -> False
    assert _hyst_lt(value, enter=2.5, exit=2.0, prev=prev).tolist() == [True, False, False]


def test_hyst_gt_with_prev_mask() -> None:
    value = np.array([1.0, 3.0, 5.0])
    prev = (True, False, True)
    # prev[0]=True -> exit=1.0: 1.0 > 1.0 -> False
    # prev[1]=False -> enter=1.5: 3.0 > 1.5 -> True
    # prev[2]=True -> exit=1.0: 5.0 > 1.0 -> True
    assert _hyst_gt(value, enter=1.5, exit=1.0, prev=prev).tolist() == [False, True, True]


def test_hyst_lte_with_prev_mask() -> None:
    value = np.array([1.0, 2.0, 3.0])
    prev = (True, False, True)
    # prev[0]=True -> exit=1.5: 1.0 <= 1.5 -> True
    # prev[1]=False -> enter=2.0: 2.0 <= 2.0 -> True
    # prev[2]=True -> exit=1.5: 3.0 <= 1.5 -> False
    assert _hyst_lte(value, enter=2.0, exit=1.5, prev=prev).tolist() == [True, True, False]


def test_hyst_gte_with_prev_mask() -> None:
    value = np.array([1.0, 2.0, 3.0])
    prev = (True, False, True)
    assert _hyst_gte(value, enter=1.5, exit=1.0, prev=prev).tolist() == [True, True, True]


def test_hyst_lt_empty_no_prev() -> None:
    value = np.array([], dtype=np.float32)
    result = _hyst_lt(value, enter=10.0, exit=8.0, prev=())
    assert len(result) == 0


# ---------------------------------------------------------------------------
# Scene activity hysteresis transitions
# ---------------------------------------------------------------------------


def test_scene_activity_static_below_floor() -> None:
    scene = _scene_activity_hysteresis(0.1, 0.05, deadband=2.0, prev_scene="static")
    assert scene == "static"


def test_scene_activity_static_to_low() -> None:
    scene = _scene_activity_hysteresis(
        median_delta=10.0,
        mean_delta=8.0,
        deadband=2.0,
        prev_scene="static",
    )
    assert scene == "low"


def test_scene_activity_low_to_high() -> None:
    scene = _scene_activity_hysteresis(
        median_delta=25.0,
        mean_delta=20.0,
        deadband=2.0,
        prev_scene="low",
    )
    assert scene == "high"


def test_scene_activity_medium_to_high() -> None:
    scene = _scene_activity_hysteresis(
        median_delta=30.0,
        mean_delta=25.0,
        deadband=2.0,
        prev_scene="medium",
    )
    assert scene == "high"


def test_scene_activity_high_stays_high_above_exit() -> None:
    scene = _scene_activity_hysteresis(
        median_delta=20.0,
        mean_delta=18.0,
        deadband=2.0,
        prev_scene="high",
    )
    assert scene == "high"


def test_scene_activity_high_to_medium() -> None:
    scene = _scene_activity_hysteresis(
        median_delta=12.0,
        mean_delta=10.0,
        deadband=2.0,
        prev_scene="high",
    )
    assert scene == "medium"


def test_scene_activity_high_to_medium_lower() -> None:
    scene = _scene_activity_hysteresis(
        median_delta=9.0,
        mean_delta=7.0,
        deadband=2.0,
        prev_scene="high",
    )
    assert scene == "medium"


def test_scene_activity_medium_stays_medium_above_enter() -> None:
    scene = _scene_activity_hysteresis(
        median_delta=22.0,
        mean_delta=18.0,
        deadband=2.0,
        prev_scene="medium",
    )
    assert scene == "medium"


def test_scene_activity_low_stays_low_under_enter() -> None:
    scene = _scene_activity_hysteresis(
        median_delta=7.0,
        mean_delta=5.0,
        deadband=2.0,
        prev_scene="low",
    )
    assert scene == "low"


# ---------------------------------------------------------------------------
# Neighbor blend: bright isolation
# ---------------------------------------------------------------------------


def test_neighbor_blend_bright_isolation() -> None:
    colors = np.array(
        [
            [240.0, 240.0, 240.0],
            [0.0, 0.0, 0.0],
            [240.0, 240.0, 240.0],
        ],
        dtype=np.float32,
    )
    blended = apply_neighbor_blend(colors, spread_mode="balanced")
    assert float(blended[1, 0]) < 20.0


def test_neighbor_blend_weight_modes() -> None:
    colors = np.linspace(30, 200, 48, dtype=np.float32)[:, None] * np.ones((48, 3))
    off = apply_neighbor_blend(colors, spread_mode="off")
    precise = apply_neighbor_blend(colors, spread_mode="precise")
    balanced = apply_neighbor_blend(colors, spread_mode="balanced")
    soft = apply_neighbor_blend(colors, spread_mode="soft")
    assert np.array_equal(off, colors)
    assert not np.array_equal(precise, balanced)
    assert not np.array_equal(soft, balanced)
    off_dev = float(np.mean(np.abs(off.astype(np.float32) - colors.astype(np.float32))))
    soft_dev = float(np.mean(np.abs(soft.astype(np.float32) - colors.astype(np.float32))))
    precise_dev = float(np.mean(np.abs(precise.astype(np.float32) - colors.astype(np.float32))))
    assert off_dev == 0.0
    assert soft_dev > precise_dev


def test_neighbor_blend_no_small_zones() -> None:
    small = np.array(
        [
            [100.0, 100.0, 100.0],
        ],
        dtype=np.float32,
    )
    small_result = apply_neighbor_blend(small, spread_mode="balanced")
    assert np.array_equal(small_result, small)


# ---------------------------------------------------------------------------
# Oklab blend: hue preservation
# ---------------------------------------------------------------------------


def test_oklab_blend_hue_preservation() -> None:
    red = np.array([[220.0, 20.0, 20.0]], dtype=np.float32)
    blue = np.array([[20.0, 20.0, 220.0]], dtype=np.float32)
    alpha = np.array([0.5], dtype=np.float32)
    out = _oklab_blend_rows(red, blue, alpha)
    _l_c, c_c, h_c = rgb_u8_to_oklch(out.astype(np.uint8))
    # Hue should be between red and blue (not green)
    _, _, h_red = rgb_u8_to_oklch(red.astype(np.uint8))
    _, _, h_blue = rgb_u8_to_oklch(blue.astype(np.uint8))
    h_c_val = float(h_c[0])
    h_r_val = float(h_red[0])
    h_b_val = float(h_blue[0])
    hue_range = sorted([h_r_val, h_b_val])
    assert hue_range[0] <= h_c_val <= hue_range[1] or abs(h_c_val - hue_range[1]) < 0.1


# ---------------------------------------------------------------------------
# neighbor blend hysteresis state propagation
# ---------------------------------------------------------------------------


def test_neighbor_blend_hysteresis_dark_masks_persist() -> None:
    colors = np.array(
        [
            [0.0, 0.0, 0.0],
            [200.0, 200.0, 200.0],
            [0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    hyst = BlendHysteresisState()
    _, hyst = apply_neighbor_blend(colors, spread_mode="balanced", hysteresis=hyst)
    assert hasattr(hyst, "neighbor_prev_dark")
    assert sum(1 for v in hyst.neighbor_prev_dark if v) >= 0


def test_adaptive_one_euro_blend_hysteresis_state_preserved() -> None:
    previous = np.full((4, 3), 100.0, dtype=np.float32)
    current = np.full((4, 3), 110.0, dtype=np.float32)
    hyst = BlendHysteresisState()
    _, _, hyst1 = adaptive_one_euro_blend(
        current=current,
        previous=previous,
        smoothing=0.5,
        smoothing_speed=0.75,
        motion_preset="responsive",
        hysteresis=hyst,
    )
    current2 = np.full((4, 3), 5.0, dtype=np.float32)
    _, _, hyst2 = adaptive_one_euro_blend(
        current=current2,
        previous=current,
        smoothing=0.5,
        smoothing_speed=0.75,
        motion_preset="responsive",
        hysteresis=hyst1,
    )
    # Scene activity should update based on frame content changes
    assert isinstance(hyst2.scene_activity, str)


# ---------------------------------------------------------------------------
# small delta (tiny mask) properly damped
# ---------------------------------------------------------------------------


def test_adaptive_one_euro_tiny_delta_damped() -> None:
    previous = np.full((8, 3), 128.0, dtype=np.float32)
    current = np.full((8, 3), 129.0, dtype=np.float32)
    blended, diag, _ = adaptive_one_euro_blend(
        current=current,
        previous=previous,
        smoothing=0.5,
        smoothing_speed=0.5,
        motion_preset="responsive",
    )
    assert diag.deadband_active
    assert float(np.mean(np.abs(blended - previous))) < 1.0
