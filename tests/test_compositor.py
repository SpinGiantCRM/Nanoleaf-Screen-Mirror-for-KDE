"""Tests for compositor SDR boost math."""

from __future__ import annotations

import numpy as np
import pytest

from nanoleaf_sync.runtime.compositor import (
    apply_sdr_boost_compensation,
    apply_zone_sdr_boost,
    effective_sdr_boost,
)


def test_effective_sdr_boost_default_80_nits() -> None:
    boost = effective_sdr_boost(sdr_boost_nits=80.0)
    assert boost == pytest.approx(1.0)


def test_effective_sdr_boost_zero() -> None:
    boost = effective_sdr_boost(sdr_boost_nits=0.0)
    assert boost == 0.0


def test_effective_sdr_boost_negative() -> None:
    boost = effective_sdr_boost(sdr_boost_nits=-50.0)
    assert boost == 0.0  # clamped to max(0, x)


def test_effective_sdr_boost_200_nits() -> None:
    boost = effective_sdr_boost(sdr_boost_nits=200.0)
    assert boost == pytest.approx(2.5)  # 200/80


def test_effective_sdr_boost_400_nits() -> None:
    boost = effective_sdr_boost(sdr_boost_nits=400.0)
    assert boost == pytest.approx(5.0)


def test_apply_sdr_boost_compensation_noop_when_boost_1() -> None:
    """When boost is <= 1, return frame unchanged."""
    frame = np.random.randint(0, 256, (100, 200, 3), dtype=np.uint8)
    result = apply_sdr_boost_compensation(frame.copy(), sdr_boost_nits=80.0, hdr_max_nits=1000.0)
    np.testing.assert_array_equal(result, frame)


def test_apply_sdr_boost_compensation_reduces_brightness() -> None:
    """Boost > 1 should darken the frame (undo compositor brightening)."""
    frame = np.full((50, 50, 3), 200, dtype=np.uint8)
    result = apply_sdr_boost_compensation(frame.copy(), sdr_boost_nits=200.0, hdr_max_nits=1000.0)
    assert result.dtype == np.uint8
    assert np.mean(result) < np.mean(frame)
    # Should still be visible (not crushed to 0)
    assert np.mean(result) > 0


def test_apply_sdr_boost_compensation_float_input() -> None:
    """Float frames should be converted to uint8."""
    frame = np.full((50, 50, 3), 128.7, dtype=np.float64)
    result = apply_sdr_boost_compensation(frame.copy(), sdr_boost_nits=200.0, hdr_max_nits=1000.0)
    assert result.dtype == np.uint8


def test_apply_sdr_boost_compensation_black_frame() -> None:
    """A black frame should stay black."""
    frame = np.zeros((50, 50, 3), dtype=np.uint8)
    result = apply_sdr_boost_compensation(frame.copy(), sdr_boost_nits=400.0, hdr_max_nits=1000.0)
    np.testing.assert_array_equal(result, frame)


def test_apply_sdr_boost_compensation_white_frame() -> None:
    """A white frame (255) should be darkened by boost compensation."""
    frame = np.full((50, 50, 3), 255, dtype=np.uint8)
    result = apply_sdr_boost_compensation(frame.copy(), sdr_boost_nits=400.0, hdr_max_nits=1000.0)
    # White should be reduced but not to 0
    assert np.max(result) < 255
    assert np.max(result) > 0


def test_apply_zone_sdr_boost_noop_when_boost_1() -> None:
    """When boost <= 1, zone colours unchanged."""
    zones = np.random.randint(0, 256, (48, 3), dtype=np.uint8)
    result = apply_zone_sdr_boost(zones.copy(), sdr_boost_nits=80.0, hdr_max_nits=1000.0)
    np.testing.assert_array_equal(result, zones)


def test_apply_zone_sdr_boost_reduces_zone_brightness() -> None:
    zones = np.full((48, 3), 200, dtype=np.uint8)
    result = apply_zone_sdr_boost(zones.copy(), sdr_boost_nits=200.0, hdr_max_nits=1000.0)
    assert np.mean(result) < 200
    assert np.mean(result) > 0


def test_apply_zone_sdr_boost_float_input() -> None:
    zones = np.full((10, 3), 100.5, dtype=np.float64)
    result = apply_zone_sdr_boost(zones.copy(), sdr_boost_nits=200.0, hdr_max_nits=1000.0)
    assert result.dtype == np.uint8


def test_apply_zone_sdr_boost_single_zone() -> None:
    """Single zone edge case."""
    zones = np.full((1, 3), 128, dtype=np.uint8)
    result = apply_zone_sdr_boost(zones.copy(), sdr_boost_nits=400.0, hdr_max_nits=1000.0)
    assert result.shape == (1, 3)
    assert result.dtype == np.uint8
