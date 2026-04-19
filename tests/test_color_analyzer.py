"""
Tests for color.analyzer — average_color, dominant_colors_kmeans, zone_colors.

These test the existing logic directly without mocking numpy internals so
that any future refactor of the analyzer is caught early.
"""

from __future__ import annotations

import numpy as np
import pytest

from nanoleaf_sync.runtime.zones import average_color, zone_colors
from nanoleaf_sync.tools.color_kmeans import dominant_colors_kmeans


# ---------------------------------------------------------------------------
# average_color
# ---------------------------------------------------------------------------


class TestAverageColor:
    def test_solid_red(self):
        img = np.full((4, 4, 3), [255, 0, 0], dtype=np.uint8)
        assert average_color(img) == (255, 0, 0)

    def test_solid_black(self):
        img = np.zeros((2, 2, 3), dtype=np.uint8)
        assert average_color(img) == (0, 0, 0)

    def test_solid_white(self):
        img = np.full((3, 3, 3), 255, dtype=np.uint8)
        assert average_color(img) == (255, 255, 255)

    def test_mixed_horizontal(self):
        # Left half red, right half blue → average is (127, 0, 127) or (128, 0, 128)
        img = np.zeros((2, 4, 3), dtype=np.uint8)
        img[:, :2, 0] = 255  # left = red
        img[:, 2:, 2] = 255  # right = blue
        r, g, b = average_color(img)
        assert g == 0
        assert r == b
        assert 120 <= r <= 135  # approx 127 or 128

    def test_single_pixel(self):
        img = np.array([[[10, 20, 30]]], dtype=np.uint8)
        assert average_color(img) == (10, 20, 30)

    def test_rejects_wrong_shape(self):
        with pytest.raises(ValueError):
            average_color(np.zeros((4, 4), dtype=np.uint8))

    def test_rejects_rgba(self):
        with pytest.raises(ValueError):
            average_color(np.zeros((4, 4, 4), dtype=np.uint8))

    def test_float_input_converted(self):
        # Passing float32 array; values should be treated as 8-bit after cast
        img = np.full((2, 2, 3), 128.0, dtype=np.float32)
        r, g, b = average_color(img)
        # After astype(uint8), 128.0 → 128
        assert r == g == b == 128


# ---------------------------------------------------------------------------
# dominant_colors_kmeans
# ---------------------------------------------------------------------------


class TestDominantColorsKmeans:
    def test_single_cluster_solid_image(self):
        img = np.full((8, 8, 3), [100, 150, 200], dtype=np.uint8)
        colors = dominant_colors_kmeans(img, n_clusters=1)
        assert len(colors) == 1
        r, g, b = colors[0]
        # Should be very close to the input color
        assert abs(r - 100) <= 2
        assert abs(g - 150) <= 2
        assert abs(b - 200) <= 2

    def test_two_dominant_clusters(self):
        # Left half pure red, right half pure blue — k=2 should find both
        img = np.zeros((16, 16, 3), dtype=np.uint8)
        img[:, :8, 0] = 255  # red
        img[:, 8:, 2] = 255  # blue
        colors = dominant_colors_kmeans(img, n_clusters=2, rng_seed=42)
        assert len(colors) == 2
        # Each cluster should be clearly red or blue
        for r, g, b in colors:
            assert g == 0
            assert (r > 200 and b < 50) or (b > 200 and r < 50)

    def test_output_count_matches_request(self):
        img = np.random.default_rng(0).integers(0, 255, (10, 10, 3), dtype=np.uint8)
        for k in (1, 3, 5):
            colors = dominant_colors_kmeans(img, n_clusters=k)
            assert len(colors) == k

    def test_values_are_valid_uint8_range(self):
        img = np.random.default_rng(1).integers(0, 255, (20, 20, 3), dtype=np.uint8)
        for r, g, b in dominant_colors_kmeans(img, n_clusters=4):
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255

    def test_raises_on_zero_clusters(self):
        img = np.zeros((4, 4, 3), dtype=np.uint8)
        with pytest.raises(ValueError):
            dominant_colors_kmeans(img, n_clusters=0)

    def test_small_image_no_crash(self):
        # 1x1 image with k > 1 should not crash
        img = np.full((1, 1, 3), [50, 60, 70], dtype=np.uint8)
        colors = dominant_colors_kmeans(img, n_clusters=3)
        assert len(colors) == 3


# ---------------------------------------------------------------------------
# zone_colors
# ---------------------------------------------------------------------------


class TestZoneColors:
    def _make_quadrant_image(self) -> np.ndarray:
        """
        4x4 image with distinct quadrant colors:
          TL=red  TR=green
          BL=blue BR=white
        """
        img = np.zeros((4, 4, 3), dtype=np.uint8)
        img[:2, :2] = [255, 0, 0]  # top-left: red
        img[:2, 2:] = [0, 255, 0]  # top-right: green
        img[2:, :2] = [0, 0, 255]  # bottom-left: blue
        img[2:, 2:] = [255, 255, 255]  # bottom-right: white
        return img

    def test_single_full_zone(self):
        img = np.full((4, 4, 3), [100, 100, 100], dtype=np.uint8)
        result = zone_colors(img, [(0, 0, 4, 4)])
        assert len(result) == 1
        # Neutral grey round-trips exactly through OKLab.
        assert result[0] == (100, 100, 100)

    def test_quadrant_zones(self):
        img = self._make_quadrant_image()
        zones = [(0, 0, 2, 2), (2, 0, 2, 2), (0, 2, 2, 2), (2, 2, 2, 2)]
        result = zone_colors(img, zones)
        # Solid primary colours: allow ±2 for OKLab float32 roundtrip.
        for channel_idx, (r, g, b) in enumerate(result[:3]):
            dominant = [r, g, b][channel_idx]
            others = [v for i, v in enumerate([r, g, b]) if i != channel_idx]
            assert abs(dominant - 255) <= 2, f"zone {channel_idx} dominant channel off: {(r, g, b)}"
            assert all(v <= 3 for v in others), f"zone {channel_idx} bleed into off channels: {(r, g, b)}"
        # White is a neutral grey; round-trips exactly.
        assert result[3] == (255, 255, 255)

    def test_empty_zones_returns_empty(self):
        img = np.zeros((4, 4, 3), dtype=np.uint8)
        assert zone_colors(img, []) == []

    def test_out_of_bounds_zone_clips_to_black(self):
        img = np.zeros((4, 4, 3), dtype=np.uint8)
        # Zone entirely outside image → (0, 0, 0)
        result = zone_colors(img, [(10, 10, 4, 4)])
        assert result == [(0, 0, 0)]

    def test_partially_clipped_zone(self):
        # Zone starts at (3,3) with size (4,4) — only 1x1 pixel inside a 4x4 image
        img = np.full((4, 4, 3), [80, 160, 240], dtype=np.uint8)
        result = zone_colors(img, [(3, 3, 4, 4)])
        assert len(result) == 1
        r, g, b = result[0]
        # Allow ±2 for OKLab float32 roundtrip on non-neutral colours.
        assert abs(r - 80) <= 2
        assert abs(g - 160) <= 2
        assert abs(b - 240) <= 2

    def test_multiple_zones_same_image(self):
        img = np.zeros((1, 6, 3), dtype=np.uint8)
        img[0, :3] = [10, 0, 0]
        img[0, 3:] = [20, 0, 0]
        result = zone_colors(img, [(0, 0, 3, 1), (3, 0, 3, 1)])
        # Very dark values: allow ±1 for sRGB linear-segment OKLab precision.
        assert abs(result[0][0] - 10) <= 1
        assert abs(result[1][0] - 20) <= 1

    def test_zone_sampling_stride_reduces_work_but_preserves_structure(self):
        img = np.zeros((8, 8, 3), dtype=np.uint8)
        img[:, :4] = [100, 0, 0]
        img[:, 4:] = [200, 0, 0]
        zones = [(0, 0, 4, 8), (4, 0, 4, 8)]

        full = zone_colors(img, zones, sample_step=1)
        fast = zone_colors(img, zones, sample_step=2)

        # Structure is preserved: left zone is redder, right zone is more red.
        # Allow ±2 for OKLab float32 roundtrip.
        assert abs(full[0][0] - 100) <= 2 and full[0][1] <= 3 and full[0][2] <= 3
        assert abs(full[1][0] - 200) <= 2 and full[1][1] <= 3 and full[1][2] <= 3
        assert abs(fast[0][0] - 100) <= 2 and fast[0][1] <= 3 and fast[0][2] <= 3
        assert abs(fast[1][0] - 200) <= 2 and fast[1][1] <= 3 and fast[1][2] <= 3
