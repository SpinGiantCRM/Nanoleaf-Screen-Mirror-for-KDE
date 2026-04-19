from __future__ import annotations

import numpy as np

from nanoleaf_sync.runtime.zones import zone_colors_array


def test_zone_averaging_uses_perceptual_oklab_midpoint() -> None:
    frame = np.array([[[255, 0, 0], [0, 0, 255]]], dtype=np.uint8)
    colors = zone_colors_array(frame, [(0, 0, 2, 1)])
    assert colors.shape == (1, 3)
    midpoint = tuple(int(c) for c in colors[0])
    # Perceptual midpoint should be a brighter magenta with non-zero green.
    assert 136 <= midpoint[0] <= 144
    assert 79 <= midpoint[1] <= 87
    assert 158 <= midpoint[2] <= 166


def test_dynamic_mode_biases_toward_vivid_highlights() -> None:
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    frame[:, :] = [40, 40, 40]
    frame[1:3, 1:3] = [255, 30, 30]

    balanced = zone_colors_array(frame, [(0, 0, 4, 4)], mode="balanced")
    dynamic = zone_colors_array(frame, [(0, 0, 4, 4)], mode="dynamic")

    assert dynamic[0, 0] > balanced[0, 0]
    assert tuple(dynamic[0]) != tuple(balanced[0])
