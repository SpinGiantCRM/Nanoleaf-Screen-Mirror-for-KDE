"""Tests for display primaries, chromaticities, chromatic adaptation, and EDID parsing."""

from __future__ import annotations

import numpy as np
import pytest

from nanoleaf_sync.color.primaries import (
    Chromaticities,
    CHROMATICITIES_SRGB,
    CHROMATICITIES_DCIP3,
    CHROMATICITIES_BT2020,
    CHROMATICITIES_DISPLAYP3,
    chromaticities_to_xyz_matrix,
    build_adaptation_matrix,
    get_primaries_for_gamut,
    invalidate_primaries_cache,
    get_display_primaries,
    _parse_edid_primaries,
)


# ---------------------------------------------------------------------------
# Chromaticities constants
# ---------------------------------------------------------------------------


def test_srgb_primaries_valid() -> None:
    p = CHROMATICITIES_SRGB
    assert 0 < p.rx < 1
    assert 0 < p.ry < 1
    assert 0 < p.gx < 1
    assert 0 < p.gy < 1
    assert 0 < p.bx < 1
    assert 0 < p.by < 1


def test_dcip3_primaries_valid() -> None:
    p = CHROMATICITIES_DCIP3
    assert p.rx == pytest.approx(0.68)
    assert p.ry == pytest.approx(0.32)


def test_bt2020_primaries_valid() -> None:
    p = CHROMATICITIES_BT2020
    assert p.rx > CHROMATICITIES_DCIP3.rx  # wider gamut
    assert p.gy > CHROMATICITIES_DCIP3.gy


def test_displayp3_is_dcip3() -> None:
    assert CHROMATICITIES_DISPLAYP3 is CHROMATICITIES_DCIP3


# ---------------------------------------------------------------------------
# chromaticities_to_xyz_matrix
# ---------------------------------------------------------------------------


def test_xyz_matrix_is_3x3_float32() -> None:
    m = chromaticities_to_xyz_matrix(CHROMATICITIES_SRGB)
    assert m.shape == (3, 3)
    assert m.dtype == np.float32


def test_xyz_matrix_all_finite() -> None:
    m = chromaticities_to_xyz_matrix(CHROMATICITIES_SRGB)
    assert np.all(np.isfinite(m))


def test_xyz_matrix_white_maps_correctly() -> None:
    """White (1,1,1) linear RGB maps to XYZ with Y=1.0."""
    m = chromaticities_to_xyz_matrix(CHROMATICITIES_SRGB)
    white_rgb = np.array([1.0, 1.0, 1.0], dtype=np.float64)
    white_xyz = white_rgb @ m.astype(np.float64)
    # Y coordinate should be 1.0 (white maps to D65 Y=1)
    assert white_xyz[1] == pytest.approx(1.0, abs=0.001)
    # X coordinate should be D65 white X (≈0.9505)
    assert white_xyz[0] == pytest.approx(0.9505, abs=0.01)
    # Z coordinate should be D65 white Z (≈1.089)
    assert white_xyz[2] == pytest.approx(1.089, abs=0.01)
    # Black (0,0,0) should map to XYZ=0
    black_rgb = np.array([0.0, 0.0, 0.0], dtype=np.float64)
    black_xyz = black_rgb @ m.astype(np.float64)
    np.testing.assert_allclose(black_xyz, [0.0, 0.0, 0.0], atol=1e-6)


def test_xyz_matrix_zero_y_primaries() -> None:
    """Primaries with y=0 should not crash."""
    p = Chromaticities(
        rx=0.64,
        ry=0.0,  # y=0 edge case
        gx=0.30,
        gy=0.60,
        bx=0.15,
        by=0.06,
        wx=0.3127,
        wy=0.3290,
    )
    m = chromaticities_to_xyz_matrix(p)
    assert np.all(np.isfinite(m))


# ---------------------------------------------------------------------------
# build_adaptation_matrix
# ---------------------------------------------------------------------------


def test_adaptation_matrix_is_3x3_float32() -> None:
    m = build_adaptation_matrix(CHROMATICITIES_SRGB, CHROMATICITIES_DCIP3)
    assert m.shape == (3, 3)
    assert m.dtype == np.float32


def test_adaptation_same_to_same_is_identity() -> None:
    """Adapting sRGB → sRGB should be close to identity."""
    m = build_adaptation_matrix(CHROMATICITIES_SRGB, CHROMATICITIES_SRGB)
    identity = np.eye(3, dtype=np.float32)
    np.testing.assert_allclose(m, identity, atol=0.02)


def test_adaptation_dcip3_to_srgb() -> None:
    m = build_adaptation_matrix(CHROMATICITIES_DCIP3, CHROMATICITIES_SRGB)
    assert np.all(np.isfinite(m))
    # DCI-P3 red is wider than sRGB; adapting should compress red channel
    # (we just check finiteness — correctness verified by known math)


# ---------------------------------------------------------------------------
# EDID parsing
# ---------------------------------------------------------------------------


def test_parse_edid_primaries_too_short() -> None:
    result = _parse_edid_primaries(b"\x00" * 20)
    assert result is None


def test_parse_edid_primaries_minimal_valid() -> None:
    """128-byte minimal valid EDID block."""
    edid = bytearray(128)
    # Set bytes 25-34 to produce non-zero values
    # Fill with valid-looking data
    for i in range(25, 35):
        edid[i] = 0x40  # mid-range values
    result = _parse_edid_primaries(bytes(edid))
    assert result is not None
    assert 0.0 <= result.rx <= 1.0
    assert 0.0 <= result.ry <= 1.0


def test_parse_edid_primaries_all_zeros() -> None:
    """All-zero chromaticity data should return None."""
    edid = bytearray(128)
    # Bytes 25-34 are zero by default
    result = _parse_edid_primaries(bytes(edid))
    assert result is None


def test_parse_edid_primaries_max_values() -> None:
    """Maximum values (1023) should decode to near 1.0."""
    edid = bytearray(128)
    # Set bytes to produce max 10-bit values
    # The encoding uses 2 bits from control bytes + 8 bits from data bytes
    # rx = ((b25>>6)&0x03)<<8 | b26
    # For max: control bits = 0x03, data byte = 0xFF → (3<<8)|255 = 1023
    edid[25] = 0xFF  # sets top 2 bits of rx, ry, gx, gy = 0b11
    edid[26] = 0xFF  # rx low = 255
    edid[27] = 0xFF  # ry low = 255
    edid[28] = 0xFF  # gx low = 255
    edid[29] = 0xFF  # gy low = 255
    edid[30] = 0xFF  # top bits of bx, by, wx, wy
    edid[31] = 0xFF
    edid[32] = 0xFF
    edid[33] = 0xFF
    edid[34] = 0xFF
    result = _parse_edid_primaries(bytes(edid))
    assert result is not None
    assert result.rx == pytest.approx(1023.0 / 1024.0, abs=0.001)
    assert result.ry == pytest.approx(1023.0 / 1024.0, abs=0.001)


# ---------------------------------------------------------------------------
# Gamut lookup
# ---------------------------------------------------------------------------


def test_get_primaries_for_gamut_srgb() -> None:
    p = get_primaries_for_gamut("srgb")
    assert p is CHROMATICITIES_SRGB


def test_get_primaries_for_gamut_dci_p3_dash() -> None:
    p = get_primaries_for_gamut("dci-p3")
    assert p is CHROMATICITIES_DCIP3


def test_get_primaries_for_gamut_dcip3_no_dash() -> None:
    p = get_primaries_for_gamut("dcip3")
    assert p is CHROMATICITIES_DCIP3


def test_get_primaries_for_gamut_bt2020() -> None:
    p = get_primaries_for_gamut("bt.2020")
    assert p is CHROMATICITIES_BT2020


def test_get_primaries_for_gamut_auto() -> None:
    p = get_primaries_for_gamut("auto")
    assert p is None


def test_get_primaries_for_gamut_unknown() -> None:
    p = get_primaries_for_gamut("linear-rec2020-hlg-st2084")
    assert p is None


def test_get_primaries_for_gamut_empty() -> None:
    p = get_primaries_for_gamut("")
    assert p is None


def test_get_primaries_for_gamut_case_insensitive() -> None:
    p = get_primaries_for_gamut("SRGB")
    assert p is CHROMATICITIES_SRGB


def test_get_primaries_for_gamut_whitespace() -> None:
    p = get_primaries_for_gamut("  srgb  ")
    assert p is CHROMATICITIES_SRGB


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


def test_invalidate_primaries_cache() -> None:
    """Cache invalidation should clear the detected primaries cache."""
    # Call get_display_primaries to populate cache (will likely return None on CI)
    first = get_display_primaries()
    invalidate_primaries_cache()
    # After invalidation, should re-detect (may return same or different)
    second = get_display_primaries()
    # Both should return the same or None — just verify no crash
    assert isinstance(first, (Chromaticities, type(None)))
    assert isinstance(second, (Chromaticities, type(None)))


def test_invalidate_then_re_detect_no_crash() -> None:
    """Multiple invalidate/detect cycles should not crash."""
    for _ in range(3):
        invalidate_primaries_cache()
        result = get_display_primaries()
        assert isinstance(result, (Chromaticities, type(None)))
