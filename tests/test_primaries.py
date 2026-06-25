"""Tests for display primaries, chromaticities, chromatic adaptation, and EDID parsing."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pytest

from nanoleaf_sync.color.primaries import (
    CHROMATICITIES_BT2020,
    CHROMATICITIES_DCIP3,
    CHROMATICITIES_DISPLAYP3,
    CHROMATICITIES_SRGB,
    Chromaticities,
    _parse_edid_primaries,
    _read_colord_profile_primaries,
    build_adaptation_matrix,
    chromaticities_to_xyz_matrix,
    get_display_primaries,
    get_display_primaries_from_sysfs,
    get_primaries_for_gamut,
    invalidate_primaries_cache,
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
    assert not np.allclose(m, np.eye(3), atol=1e-3)
    white = np.array([1.0, 1.0, 1.0], dtype=np.float32) @ m
    np.testing.assert_allclose(white, np.ones(3, dtype=np.float32), atol=1e-4)
    p3_red = np.array([1.0, 0.0, 0.0], dtype=np.float32) @ m
    assert float(p3_red[0]) > 1.0
    assert float(p3_red[1]) < 0.0


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


# ===========================================================================
# Extended tests merged from test_primaries_extended.py
# ===========================================================================

# ---------------------------------------------------------------------------
# Chromaticities constants
# ---------------------------------------------------------------------------


def test_chromaticities_srgb_values() -> None:
    p = CHROMATICITIES_SRGB
    assert p.rx == pytest.approx(0.640)
    assert p.ry == pytest.approx(0.330)
    assert p.wx == pytest.approx(0.3127)
    assert p.wy == pytest.approx(0.3290)


def test_chromaticities_dcip3_values() -> None:
    p = CHROMATICITIES_DCIP3
    assert p.rx == pytest.approx(0.680)
    assert p.gy == pytest.approx(0.690)
    assert p.wx == pytest.approx(0.3127)


def test_chromaticities_bt2020_values() -> None:
    p = CHROMATICITIES_BT2020
    assert p.rx == pytest.approx(0.708)
    assert p.gy == pytest.approx(0.797)
    assert p.by == pytest.approx(0.046)


def test_chromaticities_displayp3_equals_dcip3() -> None:
    assert CHROMATICITIES_DISPLAYP3 == CHROMATICITIES_DCIP3


def test_chromaticities_is_frozen() -> None:
    p = CHROMATICITIES_SRGB
    with pytest.raises(FrozenInstanceError):
        p.rx = 0.5  # type: ignore[misc]


def test_chromaticities_one_zero_y() -> None:
    """A single zero Y primary triggers the y==0 branch without singular matrix."""
    p = Chromaticities(
        rx=0.640, ry=0.0, gx=0.300, gy=0.600, bx=0.150, by=0.060, wx=0.3127, wy=0.3290
    )
    M = chromaticities_to_xyz_matrix(p)
    assert M.shape == (3, 3)
    assert M.dtype == np.float32
    assert np.isfinite(M).all()


def test_xyz_matrix_all_zero_chromaticities_raises() -> None:
    """All-zero chromaticities produce a singular matrix that cannot be solved."""
    p = Chromaticities(rx=0.0, ry=0.0, gx=0.0, gy=0.0, bx=0.0, by=0.0, wx=0.0, wy=0.0)
    with pytest.raises(np.linalg.LinAlgError):
        chromaticities_to_xyz_matrix(p)


# ---------------------------------------------------------------------------
# chromaticities_to_xyz_matrix
# ---------------------------------------------------------------------------


def test_xyz_matrix_white_point_reconstruction() -> None:
    """White-point reconstruction: [1,1,1] @ M should equal the white point in XYZ."""
    M = chromaticities_to_xyz_matrix(CHROMATICITIES_SRGB)
    ones = np.array([1.0, 1.0, 1.0], dtype=np.float32)
    reconstructed = ones @ M

    expected_wx_div_wy = CHROMATICITIES_SRGB.wx / CHROMATICITIES_SRGB.wy
    assert reconstructed[0] / reconstructed[1] == pytest.approx(expected_wx_div_wy, rel=1e-4)


def test_xyz_matrix_dcip3() -> None:
    M = chromaticities_to_xyz_matrix(CHROMATICITIES_DCIP3)
    assert M.shape == (3, 3)
    assert np.isfinite(M).all()


def test_xyz_matrix_bt2020() -> None:
    M = chromaticities_to_xyz_matrix(CHROMATICITIES_BT2020)
    assert M.shape == (3, 3)
    assert np.isfinite(M).all()


# ---------------------------------------------------------------------------
# build_adaptation_matrix
# ---------------------------------------------------------------------------


def test_adaptation_identity() -> None:
    """Adapting from sRGB to sRGB should produce near-identity."""
    M = build_adaptation_matrix(CHROMATICITIES_SRGB, CHROMATICITIES_SRGB)
    identity = np.eye(3, dtype=np.float32)
    np.testing.assert_allclose(M, identity, atol=1e-5)


def test_adaptation_srgb_to_dcip3() -> None:
    M = build_adaptation_matrix(CHROMATICITIES_SRGB, CHROMATICITIES_DCIP3)
    assert M.shape == (3, 3)
    assert M.dtype == np.float32
    assert np.isfinite(M).all()


def test_adaptation_dcip3_to_srgb_extended() -> None:
    M = build_adaptation_matrix(CHROMATICITIES_DCIP3, CHROMATICITIES_SRGB)
    assert M.shape == (3, 3)
    assert np.isfinite(M).all()
    assert not np.allclose(M, np.eye(3), atol=1e-3)
    white = np.array([1.0, 1.0, 1.0], dtype=np.float32) @ M
    np.testing.assert_allclose(white, np.ones(3, dtype=np.float32), atol=1e-4)


def test_adaptation_srgb_to_bt2020() -> None:
    M = build_adaptation_matrix(CHROMATICITIES_SRGB, CHROMATICITIES_BT2020)
    assert M.shape == (3, 3)
    assert np.isfinite(M).all()
    assert not np.allclose(M, np.eye(3), atol=1e-3)


def test_adaptation_default_target_is_srgb() -> None:
    M1 = build_adaptation_matrix(CHROMATICITIES_DCIP3)
    M2 = build_adaptation_matrix(CHROMATICITIES_DCIP3, CHROMATICITIES_SRGB)
    np.testing.assert_array_equal(M1, M2)


def test_adaptation_srgb_to_dcip3_combined_with_reverse_roundtrips() -> None:
    """Compose forward and reverse adaptation => near identity."""
    M_fwd = build_adaptation_matrix(CHROMATICITIES_SRGB, CHROMATICITIES_DCIP3)
    M_rev = build_adaptation_matrix(CHROMATICITIES_DCIP3, CHROMATICITIES_SRGB)
    composed = M_fwd @ M_rev
    identity = np.eye(3, dtype=np.float32)
    np.testing.assert_allclose(composed, identity, atol=1e-4)


# ---------------------------------------------------------------------------
# _parse_edid_primaries
# ---------------------------------------------------------------------------


def test_parse_edid_primaries_short_edid() -> None:
    """EDID shorter than 35 bytes should return None."""
    result = _parse_edid_primaries(b"\x00" * 34)
    assert result is None


def test_parse_edid_primaries_all_zeros_extended() -> None:
    """EDID with all-zero chromaticity block returns None."""
    edid = b"\x00" * 128
    result = _parse_edid_primaries(edid)
    assert result is None


def test_parse_edid_primaries_valid_data() -> None:
    """Valid EDID with known chromaticity values should parse correctly."""
    edid = bytearray(128)
    edid[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    edid[25] = (2 << 6) | (1 << 4) | (0 << 2) | (1 << 0)
    edid[26] = 640 & 0xFF
    edid[27] = 330 & 0xFF
    edid[28] = 300 & 0xFF
    edid[29] = 600 & 0xFF
    edid[30] = (0 << 6) | (1 << 4) | (0 << 2) | (1 << 0)
    edid[31] = 150 & 0xFF
    edid[32] = 60 & 0xFF
    edid[33] = 313 & 0xFF
    edid[34] = 329 & 0xFF

    result = _parse_edid_primaries(bytes(edid))
    assert result is not None
    assert result.rx > 0.6
    assert result.ry > 0.3


# ---------------------------------------------------------------------------
# sysfs primaries detection
# ---------------------------------------------------------------------------


def test_sysfs_primaries_no_drm_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When /sys/class/drm doesn't exist, returns None."""
    import nanoleaf_sync.color.primaries as primaries_module

    monkeypatch.setattr(
        primaries_module,
        "Path",
        type(
            "FakePath",
            (),
            {
                "__new__": lambda cls, p: tmp_path / p,
                "__truediv__": lambda self, other: tmp_path / other,
            },
        ),
    )
    result = get_display_primaries_from_sysfs()
    assert result is None or isinstance(result, Chromaticities)


def test_sysfs_primaries_with_mock_edid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock /sys/class/drm with a connected display and valid EDID."""
    drm_dir = tmp_path / "sys" / "class" / "drm"
    card_dir = drm_dir / "card0-HDMI-A-1"
    card_dir.mkdir(parents=True)

    (card_dir / "status").write_text("connected")

    edid = bytearray(128)
    edid[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    edid[25] = (2 << 6) | (1 << 4) | (0 << 2) | (1 << 0)
    edid[26] = 0x80
    edid[27] = 0x4A
    edid[28] = 0x2C
    edid[29] = 0x58
    edid[30] = (0 << 6) | (1 << 4) | (0 << 2) | (1 << 0)
    edid[31] = 0x96
    edid[32] = 0x3C
    edid[33] = 0x39
    edid[34] = 0x49
    (card_dir / "edid").write_bytes(bytes(edid))

    disconnected = drm_dir / "card0-VGA-1"
    disconnected.mkdir(parents=True)
    (disconnected / "status").write_text("disconnected")
    (disconnected / "edid").write_bytes(bytes(edid))

    original_path_class = Path

    class _FakePath(type(tmp_path)):
        def __new__(cls, *args, **kwargs):
            path_str = args[0] if args else ""
            if str(path_str).startswith("/sys/class/drm"):
                rel = str(path_str).replace("/sys/class/drm", "").lstrip("/")
                if rel:
                    return original_path_class(drm_dir / rel)
                return original_path_class(drm_dir)
            return original_path_class(*args, **kwargs)

    import nanoleaf_sync.color.primaries as primaries_module

    monkeypatch.setattr(primaries_module, "Path", _FakePath)
    result = get_display_primaries_from_sysfs()
    assert result is not None
    assert isinstance(result, Chromaticities)


# ---------------------------------------------------------------------------
# get_primaries_for_gamut
# ---------------------------------------------------------------------------


def test_get_primaries_for_gamut_srgb_extended() -> None:
    p = get_primaries_for_gamut("srgb")
    assert p == CHROMATICITIES_SRGB


def test_get_primaries_for_gamut_dci_p3() -> None:
    p = get_primaries_for_gamut("dci-p3")
    assert p == CHROMATICITIES_DCIP3


def test_get_primaries_for_gamut_dcip3_alias() -> None:
    p = get_primaries_for_gamut("dcip3")
    assert p == CHROMATICITIES_DCIP3


def test_get_primaries_for_gamut_display_p3() -> None:
    p = get_primaries_for_gamut("display-p3")
    assert p == CHROMATICITIES_DISPLAYP3


def test_get_primaries_for_gamut_bt2020_extended() -> None:
    p = get_primaries_for_gamut("bt.2020")
    assert p == CHROMATICITIES_BT2020


def test_get_primaries_for_gamut_bt2020_alias() -> None:
    p = get_primaries_for_gamut("bt2020")
    assert p == CHROMATICITIES_BT2020


def test_get_primaries_for_gamut_rec2020() -> None:
    p = get_primaries_for_gamut("rec.2020")
    assert p == CHROMATICITIES_BT2020


def test_get_primaries_for_gamut_auto_returns_none() -> None:
    assert get_primaries_for_gamut("auto") is None


def test_get_primaries_for_gamut_empty_returns_none() -> None:
    assert get_primaries_for_gamut("") is None


def test_get_primaries_for_gamut_unknown_returns_none() -> None:
    assert get_primaries_for_gamut("nonexistent-gamut") is None


def test_get_primaries_for_gamut_case_insensitive_extended() -> None:
    p = get_primaries_for_gamut("SRGB")
    assert p == CHROMATICITIES_SRGB


def test_get_primaries_for_gamut_whitespace_stripped() -> None:
    p = get_primaries_for_gamut("  srgb  ")
    assert p == CHROMATICITIES_SRGB


# ---------------------------------------------------------------------------
# get_display_primaries cache behavior
# ---------------------------------------------------------------------------


def test_display_primaries_cache_is_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    """After first call, subsequent calls should use cache (not re-probe)."""
    invalidate_primaries_cache()

    monkeypatch.setattr(
        "nanoleaf_sync.color.primaries.get_display_primaries_colord",
        lambda: None,
    )
    monkeypatch.setattr(
        "nanoleaf_sync.color.primaries.get_display_primaries_from_sysfs",
        lambda: None,
    )

    result1 = get_display_primaries()
    assert result1 is None

    monkeypatch.setattr(
        "nanoleaf_sync.color.primaries.get_display_primaries_colord",
        lambda: (_ for _ in ()).throw(RuntimeError("colord should not be called again")),
    )
    monkeypatch.setattr(
        "nanoleaf_sync.color.primaries.get_display_primaries_from_sysfs",
        lambda: (_ for _ in ()).throw(RuntimeError("sysfs should not be called again")),
    )

    result2 = get_display_primaries()
    assert result2 is None


def test_display_primaries_cache_invalidate(monkeypatch: pytest.MonkeyPatch) -> None:
    """After invalidate, probes should be called again."""
    invalidate_primaries_cache()

    call_count = [0]

    def _fake_sysfs():
        call_count[0] += 1
        return None

    monkeypatch.setattr(
        "nanoleaf_sync.color.primaries.get_display_primaries_colord",
        lambda: None,
    )
    monkeypatch.setattr(
        "nanoleaf_sync.color.primaries.get_display_primaries_from_sysfs",
        _fake_sysfs,
    )

    get_display_primaries()
    assert call_count[0] == 1

    invalidate_primaries_cache()
    get_display_primaries()
    assert call_count[0] == 2


def test_display_primaries_cache_thread_safety(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cache fill should be thread-safe (no crashes on concurrent access)."""
    import threading

    invalidate_primaries_cache()

    monkeypatch.setattr(
        "nanoleaf_sync.color.primaries.get_display_primaries_colord",
        lambda: None,
    )
    monkeypatch.setattr(
        "nanoleaf_sync.color.primaries.get_display_primaries_from_sysfs",
        lambda: None,
    )

    results = []
    barrier = threading.Barrier(4, timeout=5)

    def _worker():
        barrier.wait()
        results.append(get_display_primaries())

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert len(results) == 4
    assert all(r is None for r in results)


# ---------------------------------------------------------------------------
# _read_colord_profile_primaries error paths
# ---------------------------------------------------------------------------


def test_read_colord_profile_import_fails_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """When dbus import fails inside _read_colord_profile_primaries, returns None."""
    import builtins

    original_import = builtins.__import__

    def _fail_dbus(name, *args, **kwargs):
        if name == "dbus":
            raise ImportError("No module named dbus")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fail_dbus)
    result = _read_colord_profile_primaries(bus=object(), profile_path="/test")
    assert result is None


# ---------------------------------------------------------------------------
# _BFD and _BFD_INV constants
# ---------------------------------------------------------------------------


def test_bfd_invertibility() -> None:
    from nanoleaf_sync.color.primaries import _BFD, _BFD_INV

    identity = np.eye(3, dtype=np.float64)
    np.testing.assert_allclose(_BFD @ _BFD_INV, identity, atol=1e-6)
    np.testing.assert_allclose(_BFD_INV @ _BFD, identity, atol=1e-6)
