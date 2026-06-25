from __future__ import annotations

import numpy as np

from nanoleaf_sync.config.presets import SAMPLING_MODE_WAVELET_EDGE
from nanoleaf_sync.runtime.zones import _sample_zone_wavelet, zone_colors_array


def test_wavelet_black_white_split_prefers_white_over_area_average() -> None:
    patch = np.zeros((40, 200, 3), dtype=np.uint8)
    patch[:, 100:, :] = 255
    wavelet = _sample_zone_wavelet(patch, "top")
    area = patch.mean(axis=(0, 1)).astype(np.uint8)
    assert int(wavelet.max()) > 230
    assert int(area.max()) < 200


def test_wavelet_mode_via_zone_colors_array() -> None:
    image = np.zeros((80, 400, 3), dtype=np.uint8)
    image[:, 200:, :] = 255
    zones = [(0, 0, 400, 40)]
    colors = zone_colors_array(image, zones, sampling_mode=SAMPLING_MODE_WAVELET_EDGE)
    assert colors.shape == (1, 3)
    assert int(colors[0].max()) > 230
