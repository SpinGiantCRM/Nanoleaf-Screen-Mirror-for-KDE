"""Tests for capture utility functions."""

from __future__ import annotations

import numpy as np
import pytest

from nanoleaf_sync.capture._utils import effective_runtime_zone_count, _resize_to_target


def test_effective_zone_count_configured_wins() -> None:
    result = effective_runtime_zone_count(configured=48, detected=24)
    assert result == 48


def test_effective_zone_count_zero_configured_fallsback_to_detected() -> None:
    result = effective_runtime_zone_count(configured=0, detected=24)
    assert result == 24


def test_effective_zone_count_zero_config_zero_detected() -> None:
    result = effective_runtime_zone_count(configured=0, detected=0)
    assert result is None


def test_effective_zone_count_none_detected() -> None:
    result = effective_runtime_zone_count(configured=48, detected=None)
    assert result == 48


def test_effective_zone_count_both_none() -> None:
    result = effective_runtime_zone_count(configured=0, detected=None)
    assert result is None


def test_effective_zone_count_negative_configured_treated_as_zero() -> None:
    result = effective_runtime_zone_count(configured=-5, detected=10)
    assert result == 10  # negative cast to 0, falls back to detected


def test_resize_noop_same_dimensions() -> None:
    frame = np.random.randint(0, 256, (100, 200, 3), dtype=np.uint8)
    result = _resize_to_target(frame=frame, target_height=100, target_width=200)
    assert result is frame  # same object returned


def test_resize_scale_down() -> None:
    frame = np.random.randint(0, 256, (200, 400, 3), dtype=np.uint8)
    result = _resize_to_target(frame=frame, target_height=50, target_width=100)
    assert result.shape == (50, 100, 3)
    assert result.dtype == np.uint8


def test_resize_scale_up() -> None:
    frame = np.random.randint(0, 256, (50, 100, 3), dtype=np.uint8)
    result = _resize_to_target(frame=frame, target_height=200, target_width=400)
    assert result.shape == (200, 400, 3)


def test_resize_preserves_colors_approximately() -> None:
    """A uniform-colour region should survive resize with similar values."""
    frame = np.full((100, 200, 3), 128, dtype=np.uint8)
    result = _resize_to_target(frame=frame, target_height=50, target_width=100)
    # Nearest-neighbour indexing from all-128 frame keeps values exactly
    assert np.allclose(np.mean(result), 128.0, atol=0.5)


def test_resize_with_index_cache() -> None:
    cache: dict[tuple[int, int, int, int], tuple[np.ndarray, np.ndarray]] = {}
    frame = np.random.randint(0, 256, (100, 200, 3), dtype=np.uint8)
    result1 = _resize_to_target(frame=frame, target_height=50, target_width=100, index_cache=cache)
    assert (100, 200, 50, 100) in cache  # cache populated
    result2 = _resize_to_target(frame=frame, target_height=50, target_width=100, index_cache=cache)
    assert result1.shape == result2.shape


def test_resize_cache_limit_eviction() -> None:
    cache: dict[tuple[int, int, int, int], tuple[np.ndarray, np.ndarray]] = {}
    # Fill beyond cache limit (default 8)
    for i in range(15):
        h = 50 + i
        frame = np.random.randint(0, 256, (h, 200, 3), dtype=np.uint8)
        _resize_to_target(frame=frame, target_height=25 + i, target_width=100, index_cache=cache)
    assert len(cache) <= 8


def test_resize_single_channel_non_rgb() -> None:
    """Non-3-channel frames: verify the function requires 3D input."""
    frame = np.random.randint(0, 256, (100, 200), dtype=np.uint8)
    with pytest.raises(IndexError):
        _resize_to_target(frame=frame, target_height=50, target_width=100)
