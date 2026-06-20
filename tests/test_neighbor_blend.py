from __future__ import annotations

import numpy as np

from nanoleaf_sync.runtime.blending import apply_neighbor_blend


def test_dark_zones_unaffected_by_bright_neighbor() -> None:
    colors = np.zeros((24, 3), dtype=np.float32)
    colors[0] = np.array([240.0, 40.0, 220.0], dtype=np.float32)
    out = apply_neighbor_blend(colors, spread_mode="precise")
    for idx in range(2, 24):
        assert float(np.max(out[idx])) < 1.0


def test_dim_neutral_zones_unaffected_by_bright_neighbor() -> None:
    colors = np.full((24, 3), np.array([32.0, 31.0, 33.0], dtype=np.float32))
    colors[0] = np.array([240.0, 40.0, 220.0], dtype=np.float32)
    out = apply_neighbor_blend(colors, spread_mode="soft")
    np.testing.assert_allclose(out[1:], colors[1:], atol=0.01)


def test_no_wrap_from_last_index_into_first() -> None:
    colors = np.zeros((24, 3), dtype=np.float32)
    colors[-1] = np.array([240.0, 40.0, 220.0], dtype=np.float32)
    out = apply_neighbor_blend(colors, spread_mode="precise")
    assert float(np.max(out[0])) < 1.0


def test_bright_zone_keeps_spread_from_adjacent_bright() -> None:
    colors = np.full((24, 3), 4.0, dtype=np.float32)
    colors[0] = np.array([240.0, 40.0, 220.0], dtype=np.float32)
    colors[1] = np.array([230.0, 50.0, 210.0], dtype=np.float32)
    out = apply_neighbor_blend(colors, spread_mode="precise")
    assert float(np.max(out[0])) > 200.0
    assert float(np.max(out[1])) > 200.0


def test_tint_does_not_propagate_past_second_zone_over_frames() -> None:
    colors = np.zeros((24, 3), dtype=np.float32)
    colors[0] = np.array([240.0, 40.0, 220.0], dtype=np.float32)
    state = colors.copy()
    for _ in range(10):
        state = apply_neighbor_blend(state, spread_mode="precise")
    for idx in range(2, 24):
        assert float(np.max(state[idx])) < 8.0
