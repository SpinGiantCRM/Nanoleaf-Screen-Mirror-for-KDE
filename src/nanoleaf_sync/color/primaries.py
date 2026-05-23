"""
Display primaries detection and chromatic adaptation.

Supports:
- EDID-based detection via ``/sys/class/drm/*/edid``
- colord D-Bus detection (preferred when available)
- sRGB, DCI-P3, BT.2020 reference primaries
- Bradford chromatic adaptation matrix construction
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Primaries constants
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Chromaticities:
    """CIE 1931 xy chromaticity coordinates for RGB primaries and white point."""

    rx: float
    ry: float
    gx: float
    gy: float
    bx: float
    by: float
    wx: float
    wy: float


# sRGB / BT.709 primaries (D65 white point).
CHROMATICITIES_SRGB = Chromaticities(
    rx=0.640,
    ry=0.330,
    gx=0.300,
    gy=0.600,
    bx=0.150,
    by=0.060,
    wx=0.3127,
    wy=0.3290,
)

# DCI-P3 (D65 white point).
CHROMATICITIES_DCIP3 = Chromaticities(
    rx=0.680,
    ry=0.320,
    gx=0.265,
    gy=0.690,
    bx=0.150,
    by=0.060,
    wx=0.3127,
    wy=0.3290,
)

# BT.2020 (D65 white point).
CHROMATICITIES_BT2020 = Chromaticities(
    rx=0.708,
    ry=0.292,
    gx=0.170,
    gy=0.797,
    bx=0.131,
    by=0.046,
    wx=0.3127,
    wy=0.3290,
)

# Display P3 (same primaries as DCI-P3 but D65 white).
CHROMATICITIES_DISPLAYP3 = CHROMATICITIES_DCIP3


# ---------------------------------------------------------------------------
# Chromaticity → XYZ matrix
# ---------------------------------------------------------------------------


def chromaticities_to_xyz_matrix(p: Chromaticities) -> np.ndarray:
    """Build a 3×3 row-major XYZ-from-linear-RGB matrix for the given primaries.

    Returns a ``(3, 3)`` ``float32`` array where ``xyz = rgb @ M``.
    """
    # Primary chromaticities → XYZ primaries (Y = 1 columns).
    rx, ry = p.rx, p.ry
    gx, gy = p.gx, p.gy
    bx, by = p.bx, p.by

    def _xyz_from_xy(x: float, y: float) -> tuple[float, float, float]:
        if y == 0.0:
            return (x, 1.0, 0.0)
        return (x / y, 1.0, (1.0 - x - y) / y)

    Xr, _Yr, Zr = _xyz_from_xy(rx, ry)
    Xg, _Yg, Zg = _xyz_from_xy(gx, gy)
    Xb, _Yb, Zb = _xyz_from_xy(bx, by)

    # Build the 3×3 matrix with primaries as *rows* (rgb @ M = xyz).
    M = np.array(
        [
            [Xr, 1.0, Zr],
            [Xg, 1.0, Zg],
            [Xb, 1.0, Zb],
        ],
        dtype=np.float64,
    )

    # White point → XYZ.
    Wx, Wy = p.wx, p.wy
    if Wy == 0.0:
        W_xyz = np.array([Wx, 1.0, 0.0], dtype=np.float64)
    else:
        W_xyz = np.array([Wx / Wy, 1.0, (1.0 - Wx - Wy) / Wy], dtype=np.float64)

    # Solve for scaling factors: Mᵀ @ S = W_xyz → S = (Mᵀ)⁻¹ @ W_xyz.
    S = np.linalg.solve(M.T, W_xyz)

    # Scale rows of M so that [1,1,1] @ M_scaled = M @ S = W_xyz.
    M_scaled = M * S[:, None]  # broadcast: (3,3) * (3,1) → scale each row

    return M_scaled.astype(np.float32)


# ---------------------------------------------------------------------------
# Bradford chromatic adaptation
# ---------------------------------------------------------------------------

# Bradford cone response matrix (row-major: cone = xyz @ BFD)
_BFD = np.array(
    [
        [0.8951, 0.2664, -0.1614],
        [-0.7502, 1.7135, 0.0367],
        [0.0389, -0.0685, 1.0296],
    ],
    dtype=np.float64,
)

_BFD_INV = np.array(
    [
        [0.9869929, -0.1470543, 0.1599627],
        [0.4323053, 0.5183603, 0.0492912],
        [-0.0085287, 0.0400428, 0.9684867],
    ],
    dtype=np.float64,
)


def build_adaptation_matrix(
    src_primaries: Chromaticities,
    target_primaries: Chromaticities = CHROMATICITIES_SRGB,
) -> np.ndarray:
    """Build a 3×3 Bradford adaptation matrix from *src* to *target* primaries.

    Returns ``(3, 3)`` ``float32`` matrix: ``rgb_target = rgb_src @ M``
    (applied to linear RGB values, row-vector convention).
    """
    src_xyz = chromaticities_to_xyz_matrix(src_primaries)
    tgt_xyz = chromaticities_to_xyz_matrix(target_primaries)

    # Extract white points as XYZ (white = R+G+B at equal intensity).
    # With row-major matrices, [1,1,1] @ M = sum of rows (axis=0) = W_xyz.
    src_white = np.sum(src_xyz, axis=0)
    tgt_white = np.sum(tgt_xyz, axis=0)

    # Cone responses for white points.
    src_cone = _BFD @ src_white
    tgt_cone = _BFD @ tgt_white

    # Diagonal scaling matrix (tgt_cone / src_cone).
    with np.errstate(divide="ignore", invalid="ignore"):
        scale = np.where(np.abs(src_cone) > 1e-12, tgt_cone / src_cone, 1.0)

    D = np.diag(scale)

    # Full Bradford: BFD⁻¹ @ D @ BFD.
    M = _BFD_INV @ D @ _BFD
    return M.astype(np.float32)


# ---------------------------------------------------------------------------
# EDID parsing
# ---------------------------------------------------------------------------


def _parse_edid_primaries(edid_bytes: bytes) -> Chromaticities | None:
    """Parse chromaticity coordinates from a raw 128-byte EDID block.

    Returns ``None`` if the EDID is too short or the chromaticity block
    contains invalid (zero) data.
    """
    if len(edid_bytes) < 35:
        return None

    # Bytes 25-34 contain the chromaticity block (10 bytes).
    b25 = edid_bytes[25]
    b26 = edid_bytes[26]
    b27 = edid_bytes[27]
    b28 = edid_bytes[28]
    b29 = edid_bytes[29]
    b30 = edid_bytes[30]
    b31 = edid_bytes[31]
    b32 = edid_bytes[32]
    b33 = edid_bytes[33]
    b34 = edid_bytes[34]

    # Decode 10-bit values.
    rx = ((b25 >> 6) & 0x03) << 8 | b26
    ry = ((b25 >> 4) & 0x03) << 8 | b27
    gx = ((b25 >> 2) & 0x03) << 8 | b28
    gy = ((b25 >> 0) & 0x03) << 8 | b29
    bx = ((b30 >> 6) & 0x03) << 8 | b31
    by = ((b30 >> 4) & 0x03) << 8 | b32
    wx = ((b30 >> 2) & 0x03) << 8 | b33
    wy = ((b30 >> 0) & 0x03) << 8 | b34

    # Check for all zeros (invalid/uninitialised).
    values = (rx, ry, gx, gy, bx, by, wx, wy)
    if all(v == 0 for v in values):
        return None

    # Convert from 10-bit (0-1023) to float in [0, 1].
    return Chromaticities(
        rx=rx / 1024.0,
        ry=ry / 1024.0,
        gx=gx / 1024.0,
        gy=gy / 1024.0,
        bx=bx / 1024.0,
        by=by / 1024.0,
        wx=wx / 1024.0,
        wy=wy / 1024.0,
    )


def get_display_primaries_from_sysfs() -> Chromaticities | None:
    """Read EDID from ``/sys/class/drm/*/edid`` and parse primaries.

    Returns the first valid EDID found, or ``None``.
    """
    drm_root = Path("/sys/class/drm")
    if not drm_root.is_dir():
        return None

    for entry in sorted(drm_root.iterdir()):
        if not entry.is_dir():
            continue
        edid_path = entry / "edid"
        if not edid_path.is_file():
            continue
        # Skip write-only connectors (they don't have connected displays).
        status_path = entry / "status"
        if status_path.is_file():
            try:
                status = status_path.read_text().strip()
                if status.lower() != "connected":
                    continue
            except OSError:
                pass
        try:
            raw = edid_path.read_bytes()
        except OSError:
            continue
        primaries = _parse_edid_primaries(raw)
        if primaries is not None:
            _log.debug(
                "Display primaries from sysfs %s: r=(%.3f,%.3f) g=(%.3f,%.3f) b=(%.3f,%.3f) w=(%.3f,%.3f)",
                edid_path,
                primaries.rx,
                primaries.ry,
                primaries.gx,
                primaries.gy,
                primaries.bx,
                primaries.by,
                primaries.wx,
                primaries.wy,
            )
            return primaries

    return None


# ---------------------------------------------------------------------------
# colord D-Bus detection
# ---------------------------------------------------------------------------


def get_display_primaries_colord() -> Chromaticities | None:
    """Query colord over D-Bus for the default display profile primaries.

    Requires ``org.freedesktop.ColorManager`` on the session bus.
    Returns ``None`` if colord is unavailable or returns no profiles.
    """
    try:
        import dbus
    except ImportError:
        _log.debug("colord: python-dbus not installed; skipping D-Bus detection")
        return None

    try:
        bus = dbus.SessionBus()
    except dbus.DBusException:
        _log.debug("colord: no D-Bus session bus available")
        return None

    try:
        cm = bus.get_object(
            "org.freedesktop.ColorManager",
            "/org/freedesktop/ColorManager",
        )
        cm_iface = dbus.Interface(
            cm,
            "org.freedesktop.ColorManager",
        )
    except dbus.DBusException:
        _log.debug("colord: ColorManager not available on D-Bus")
        return None

    try:
        devices = cm_iface.GetDevices()
    except dbus.DBusException:
        _log.debug("colord: GetDevices failed")
        return None

    for device_path in devices:
        try:
            dev = bus.get_object("org.freedesktop.ColorManager", device_path)
            dev_iface = dbus.Interface(dev, "org.freedesktop.ColorManager.Device")
            profile_path = dev_iface.GetDefaultProfile()
        except dbus.DBusException:
            continue

        if not profile_path:
            continue

        primaries = _read_colord_profile_primaries(bus, str(profile_path))
        if primaries is not None:
            return primaries

    return None


def _read_colord_profile_primaries(
    bus: Any,
    profile_path: str,
) -> Chromaticities | None:
    """Read primaries from a colord profile object path.

    Supports both the ``RedPrimary``/... properties and the
    ``Primaries`` property (array of 6 doubles).
    """
    try:
        import dbus
    except ImportError:
        return None

    try:
        profile = bus.get_object("org.freedesktop.ColorManager", profile_path)
        props_iface = dbus.Interface(profile, "org.freedesktop.DBus.Properties")
    except dbus.DBusException:
        return None

    # Try the individual *Primary properties first.
    try:
        red = props_iface.Get("org.freedesktop.ColorManager.Profile", "RedPrimary")
        green = props_iface.Get("org.freedesktop.ColorManager.Profile", "GreenPrimary")
        blue = props_iface.Get("org.freedesktop.ColorManager.Profile", "BluePrimary")
        white = props_iface.Get("org.freedesktop.ColorManager.Profile", "WhitePrimary")
        if red and green and blue and white:
            return Chromaticities(
                rx=float(red[0]),
                ry=float(red[1]),
                gx=float(green[0]),
                gy=float(green[1]),
                bx=float(blue[0]),
                by=float(blue[1]),
                wx=float(white[0]),
                wy=float(white[1]),
            )
    except dbus.DBusException:
        pass

    # Try the Primaries property (array of 6: rx, ry, gx, gy, bx, by).
    try:
        prim = props_iface.Get("org.freedesktop.ColorManager.Profile", "Primaries")
        if prim and len(prim) >= 6:
            # White point defaults to D65.
            return Chromaticities(
                rx=float(prim[0]),
                ry=float(prim[1]),
                gx=float(prim[2]),
                gy=float(prim[3]),
                bx=float(prim[4]),
                by=float(prim[5]),
                wx=0.3127,
                wy=0.3290,
            )
    except dbus.DBusException:
        pass

    return None


# ---------------------------------------------------------------------------
# Unified detection
# ---------------------------------------------------------------------------

_PRIMARIES_BY_GAMUT: dict[str, Chromaticities] = {
    "srgb": CHROMATICITIES_SRGB,
    "dci-p3": CHROMATICITIES_DCIP3,
    "dcip3": CHROMATICITIES_DCIP3,
    "display-p3": CHROMATICITIES_DISPLAYP3,
    "displayp3": CHROMATICITIES_DISPLAYP3,
    "bt.2020": CHROMATICITIES_BT2020,
    "bt2020": CHROMATICITIES_BT2020,
    "rec.2020": CHROMATICITIES_BT2020,
    "rec2020": CHROMATICITIES_BT2020,
}

_DETECTED_PRIMARIES_CACHE: Chromaticities | None = None
_DETECTED_PRIMARIES_FILLED: bool = False
_DETECTED_PRIMARIES_LOCK = threading.Lock()


def get_display_primaries() -> Chromaticities | None:
    """Detect display primaries, preferring colord then EDID sysfs.

    Results are cached for the lifetime of the process.
    """
    global _DETECTED_PRIMARIES_CACHE, _DETECTED_PRIMARIES_FILLED

    # Fast path: cache already populated, read outside lock (safe because
    # once _FILLED is True the cache pointer is never mutated to None).
    if _DETECTED_PRIMARIES_FILLED:
        return _DETECTED_PRIMARIES_CACHE

    with _DETECTED_PRIMARIES_LOCK:
        # Re-check under lock in case another thread finished detection.
        if _DETECTED_PRIMARIES_FILLED:
            return _DETECTED_PRIMARIES_CACHE

        primaries = get_display_primaries_colord()
        if primaries is not None:
            _DETECTED_PRIMARIES_CACHE = primaries
            _DETECTED_PRIMARIES_FILLED = True
            return primaries

        primaries = get_display_primaries_from_sysfs()
        _DETECTED_PRIMARIES_CACHE = primaries  # None if no EDID found
        _DETECTED_PRIMARIES_FILLED = True
        return primaries


def get_primaries_for_gamut(gamut: str) -> Chromaticities | None:
    """Look up chromaticities for a named gamut preset.

    Returns ``None`` for ``"auto"`` or unrecognised names.
    """
    if not gamut or gamut == "auto":
        return None
    return _PRIMARIES_BY_GAMUT.get(gamut.strip().lower())


def invalidate_primaries_cache() -> None:
    """Reset the detected-primaries cache (e.g. after display reconnect)."""
    global _DETECTED_PRIMARIES_CACHE, _DETECTED_PRIMARIES_FILLED
    with _DETECTED_PRIMARIES_LOCK:
        _DETECTED_PRIMARIES_CACHE = None
        _DETECTED_PRIMARIES_FILLED = False
