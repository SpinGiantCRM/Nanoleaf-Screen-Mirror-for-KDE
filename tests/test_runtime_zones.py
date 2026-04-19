from __future__ import annotations

import numpy as np

from nanoleaf_sync.runtime.zones import zone_colors_array


def test_zone_averaging_uses_perceptual_oklab_midpoint() -> None:
    frame = np.array([[[255, 0, 0], [0, 0, 255]]], dtype=np.uint8)
    colors = zone_colors_array(frame, [(0, 0, 2, 1)])
    assert colors.shape == (1, 3)
    midpoint = tuple(int(c) for c in colors[0])
    # Perceptual midpoint should not collapse to naive sRGB (127, 0, 127).
    assert midpoint != (127, 0, 127)
    assert midpoint[0] > 120 and midpoint[2] > 120
