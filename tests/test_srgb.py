"""Tests for sRGB ↔ linear light conversion functions."""

from __future__ import annotations

import numpy as np
import pytest

from nanoleaf_sync.runtime.srgb import (
    linear01_to_srgb_encoded,
    linear01_to_srgb_u8,
    srgb_eotf_to_linear01,
    srgb_u8_to_linear01,
)

# -- srgb_eotf_to_linear01 ------------------------------------------------


def test_srgb_eotf_black_is_zero() -> None:
    result = srgb_eotf_to_linear01(np.array([0.0], dtype=np.float32))
    assert result[0] == 0.0


def test_srgb_eotf_white_is_one() -> None:
    result = srgb_eotf_to_linear01(np.array([1.0], dtype=np.float32))
    assert result[0] == pytest.approx(1.0, abs=0.001)


def test_srgb_eotf_mid_gray_rises() -> None:
    """0.5 encoded should be < 0.25 linear (gamma > 1)."""
    result = srgb_eotf_to_linear01(np.array([0.5], dtype=np.float32))
    assert 0.1 < result[0] < 0.3


def test_srgb_eotf_threshold_boundary() -> None:
    """Values just above threshold use the power curve."""
    below = np.array([0.04044], dtype=np.float32)
    above = np.array([0.04046], dtype=np.float32)
    r_below = srgb_eotf_to_linear01(below)
    r_above = srgb_eotf_to_linear01(above)
    # Should be continuous (close values)
    assert pytest.approx(r_below[0], abs=0.001) == r_above[0]


def test_srgb_eotf_ndarray_many() -> None:
    c = np.linspace(0.0, 1.0, 100, dtype=np.float32)
    result = srgb_eotf_to_linear01(c)
    assert result.shape == (100,)
    assert result.dtype == np.float32
    assert np.all(result >= 0.0)
    # Monotonically increasing
    assert np.all(np.diff(result) >= 0.0)


# -- linear01_to_srgb_encoded ----------------------------------------------


def test_linear_to_srgb_black() -> None:
    result = linear01_to_srgb_encoded(np.array([0.0], dtype=np.float32))
    assert result[0] == 0.0


def test_linear_to_srgb_white() -> None:
    result = linear01_to_srgb_encoded(np.array([1.0], dtype=np.float32))
    assert pytest.approx(result[0], abs=0.001) == 1.0


def test_linear_to_srgb_clamped_to_0_1() -> None:
    linear = np.array([-0.5, 0.5, 2.0], dtype=np.float32)
    result = linear01_to_srgb_encoded(linear)
    assert np.all(result >= 0.0)
    assert np.all(result <= 1.0)


def test_linear_to_srgb_negative_clipped() -> None:
    result = linear01_to_srgb_encoded(np.array([-100.0], dtype=np.float32))
    assert result[0] == 0.0


# -- round-trip ------------------------------------------------------------


def test_srgb_roundtrip_identity_ish() -> None:
    """sRGB → linear → sRGB should approximately restore original values."""
    values = np.linspace(0.0, 1.0, 50, dtype=np.float32)
    linear = srgb_eotf_to_linear01(values)
    encoded = linear01_to_srgb_encoded(linear)
    np.testing.assert_allclose(encoded, values, atol=0.001)


# -- srgb_u8_to_linear01 ---------------------------------------------------


def test_srgb_u8_black() -> None:
    result = srgb_u8_to_linear01(np.array([0], dtype=np.uint8))
    assert result[0] == pytest.approx(0.0, abs=1e-6)


def test_srgb_u8_white() -> None:
    result = srgb_u8_to_linear01(np.array([255], dtype=np.uint8))
    assert result[0] == pytest.approx(1.0, abs=0.002)


def test_srgb_u8_float_input_fallsback() -> None:
    """Float input (0-255 range) uses eotf path instead of LUT."""
    result = srgb_u8_to_linear01(np.array([128.0], dtype=np.float64))
    assert 0.15 < result[0] < 0.25


def test_srgb_u8_2d_array() -> None:
    frame = np.full((10, 10, 3), 128, dtype=np.uint8)
    result = srgb_u8_to_linear01(frame)
    assert result.shape == (10, 10, 3)
    assert result.dtype == np.float32
    assert 0.15 < result[0, 0, 0] < 0.3


# -- linear01_to_srgb_u8 ---------------------------------------------------


def test_linear_to_srgb_u8_black() -> None:
    result = linear01_to_srgb_u8(np.array([0.0], dtype=np.float32))
    assert result[0] == 0


def test_linear_to_srgb_u8_white() -> None:
    result = linear01_to_srgb_u8(np.array([1.0], dtype=np.float32))
    assert result[0] == 255


def test_linear_to_srgb_u8_dtype() -> None:
    result = linear01_to_srgb_u8(np.array([0.5, 0.3, 0.1], dtype=np.float32))
    assert result.dtype == np.uint8


def test_linear_to_srgb_u8_negative_input() -> None:
    result = linear01_to_srgb_u8(np.array([-10.0], dtype=np.float64))
    assert result[0] == 0
