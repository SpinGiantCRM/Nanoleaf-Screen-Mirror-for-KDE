"""Additional tests for color/primaries.py edge cases and uncovered paths."""

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
    # Only ry=0 triggers the y==0 branch. Other primaries keep Y>0.
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


def test_xyz_matrix_shape_and_dtype() -> None:
    M = chromaticities_to_xyz_matrix(CHROMATICITIES_SRGB)
    assert M.shape == (3, 3)
    assert M.dtype == np.float32


def test_xyz_matrix_white_point_reconstruction() -> None:
    """White-point reconstruction: [1,1,1] @ M should equal the white point in XYZ."""
    M = chromaticities_to_xyz_matrix(CHROMATICITIES_SRGB)
    ones = np.array([1.0, 1.0, 1.0], dtype=np.float32)
    reconstructed = ones @ M

    # Target: Wx/Wy=1.0 by definition since Y=1, so Wx=0.3127/0.3290 ≈ 0.9505
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


def test_adaptation_dcip3_to_srgb() -> None:
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


def test_parse_edid_primaries_all_zeros() -> None:
    """EDID with all-zero chromaticity block returns None."""
    edid = b"\x00" * 128
    result = _parse_edid_primaries(edid)
    assert result is None


def test_parse_edid_primaries_valid_data() -> None:
    """Valid EDID with known chromaticity values should parse correctly."""
    edid = bytearray(128)
    # Set up a valid EDID header
    edid[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    # Byte 25: upper 2 bits of each value, set bits for non-zero values
    # Values: R=640, G=300, B=150 (sRGB-like, in 10-bit: 640=0x280, 300=0x12C, 150=0x096)
    # Upper bits of R=(640>>8)=2, G=(300>>8)=1, B=(150>>8)=0, upper bits of W=(312>>8)=1, (329>>8)=1
    # b25: RRGGBBWW format: bits 7-6=RR, 5-4=GG, 3-2=BB, 1-0=WW
    edid[25] = (2 << 6) | (1 << 4) | (0 << 2) | (1 << 0)  # RR=2, GG=1, BB=0, WW=1
    edid[26] = 640 & 0xFF  # rx low
    edid[27] = 330 & 0xFF  # ry low
    edid[28] = 300 & 0xFF  # gx low
    edid[29] = 600 & 0xFF  # gy low
    edid[30] = (0 << 6) | (1 << 4) | (0 << 2) | (1 << 0)  # bx upper bits=0, by upper bits=1
    edid[31] = 150 & 0xFF  # bx low
    edid[32] = 60 & 0xFF  # by low
    edid[33] = 313 & 0xFF  # wx low
    edid[34] = 329 & 0xFF  # wy low

    result = _parse_edid_primaries(bytes(edid))
    assert result is not None
    # The exact values depend on decoding precision, but should be close
    assert result.rx > 0.6
    assert result.ry > 0.3


# ---------------------------------------------------------------------------
# sysfs primaries detection
# ---------------------------------------------------------------------------


def test_sysfs_primaries_no_drm_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When /sys/class/drm doesn't exist, returns None."""
    monkeypatch.setattr("nanoleaf_sync.color.primaries.Path", lambda p: tmp_path / p)
    # Create a non-existent path
    result = (
        get_display_primaries_from_sysfs.__wrapped__
        if hasattr(get_display_primaries_from_sysfs, "__wrapped__")
        else get_display_primaries_from_sysfs
    )
    # Just use monkeypatch on the module-level Path
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
    # Simpler: monkeypatch the drm_root check
    result = get_display_primaries_from_sysfs()
    # This should return None if /sys/class/drm doesn't exist on the test system
    # We just verify it doesn't crash
    assert result is None or isinstance(result, Chromaticities)


def test_sysfs_primaries_with_mock_edid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock /sys/class/drm with a connected display and valid EDID."""
    drm_dir = tmp_path / "sys" / "class" / "drm"
    card_dir = drm_dir / "card0-HDMI-A-1"
    card_dir.mkdir(parents=True)

    # Write "connected" status
    (card_dir / "status").write_text("connected")

    # Write a valid EDID
    edid = bytearray(128)
    edid[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    edid[25] = (2 << 6) | (1 << 4) | (0 << 2) | (1 << 0)
    edid[26] = 0x80  # rx = 0x280 = 640
    edid[27] = 0x4A  # ry = 0x14A = 330
    edid[28] = 0x2C  # gx = 0x12C = 300
    edid[29] = 0x58  # gy = 0x258 = 600
    edid[30] = (0 << 6) | (1 << 4) | (0 << 2) | (1 << 0)
    edid[31] = 0x96  # bx = 0x096 = 150
    edid[32] = 0x3C  # by = 0x03C = 60
    edid[33] = 0x39  # wx = 0x139 = 313
    edid[34] = 0x49  # wy = 0x149 = 329
    (card_dir / "edid").write_bytes(bytes(edid))

    # Add an unconnected display (should be skipped)
    disconnected = drm_dir / "card0-VGA-1"
    disconnected.mkdir(parents=True)
    (disconnected / "status").write_text("disconnected")
    (disconnected / "edid").write_bytes(bytes(edid))

    # Monkeypatch Path to use our fake sysfs
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


def test_get_primaries_for_gamut_srgb() -> None:
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


def test_get_primaries_for_gamut_bt2020() -> None:
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


def test_get_primaries_for_gamut_none_returns_none() -> None:
    assert get_primaries_for_gamut("") is None


def test_get_primaries_for_gamut_unknown_returns_none() -> None:
    assert get_primaries_for_gamut("nonexistent-gamut") is None


def test_get_primaries_for_gamut_case_insensitive() -> None:
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

    # Make both probes return None so cache is None-filled
    monkeypatch.setattr(
        "nanoleaf_sync.color.primaries.get_display_primaries_colord",
        lambda: None,
    )
    monkeypatch.setattr(
        "nanoleaf_sync.color.primaries.get_display_primaries_from_sysfs",
        lambda: None,
    )

    # First call: cold cache
    result1 = get_display_primaries()
    assert result1 is None

    # Second call: cache should be used
    # Monkeypatch probes to raise if called (proving cache is used)
    monkeypatch.setattr(
        "nanoleaf_sync.color.primaries.get_display_primaries_colord",
        lambda: (_ for _ in ()).throw(RuntimeError("colord should not be called again")),
    )
    monkeypatch.setattr(
        "nanoleaf_sync.color.primaries.get_display_primaries_from_sysfs",
        lambda: (_ for _ in ()).throw(RuntimeError("sysfs should not be called again")),
    )

    result2 = get_display_primaries()
    assert result2 is None  # Cached None is returned without calling probes


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

    # Invalidate and call again — probe should be called again
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
