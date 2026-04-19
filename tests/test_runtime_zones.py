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


def test_dynamic_mode_requires_stronger_signal_in_brighter_scene() -> None:
    dark_frame = np.zeros((6, 6, 3), dtype=np.uint8)
    dark_frame[:, :] = [25, 25, 25]
    dark_frame[2:4, 2:4] = [180, 40, 40]

    bright_frame = np.zeros((6, 6, 3), dtype=np.uint8)
    bright_frame[:, :] = [170, 170, 170]
    bright_frame[2:4, 2:4] = [220, 130, 130]

    dark_balanced = zone_colors_array(dark_frame, [(0, 0, 6, 6)], mode="balanced")
    dark_dynamic = zone_colors_array(dark_frame, [(0, 0, 6, 6)], mode="dynamic")
    bright_balanced = zone_colors_array(bright_frame, [(0, 0, 6, 6)], mode="balanced")
    bright_dynamic = zone_colors_array(bright_frame, [(0, 0, 6, 6)], mode="dynamic")

    dark_red_lift = int(dark_dynamic[0, 0]) - int(dark_balanced[0, 0])
    bright_red_lift = int(bright_dynamic[0, 0]) - int(bright_balanced[0, 0])

    assert dark_red_lift > bright_red_lift


def test_color_modes_are_meaningfully_different() -> None:
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    frame[:, :] = [30, 30, 30]
    frame[2:6, 2:6] = [255, 50, 40]

    balanced = zone_colors_array(frame, [(0, 0, 8, 8)], mode="balanced")[0]
    default = zone_colors_array(frame, [(0, 0, 8, 8)], mode="default")[0]
    dynamic = zone_colors_array(frame, [(0, 0, 8, 8)], mode="dynamic")[0]
    hyper = zone_colors_array(frame, [(0, 0, 8, 8)], mode="hyper")[0]

    assert int(default[0]) >= int(balanced[0])
    assert int(dynamic[0]) >= int(default[0])
    assert int(hyper[0]) >= int(dynamic[0])
    assert tuple(default) != tuple(balanced)
    assert tuple(dynamic) != tuple(default)
    assert tuple(hyper) != tuple(dynamic)
