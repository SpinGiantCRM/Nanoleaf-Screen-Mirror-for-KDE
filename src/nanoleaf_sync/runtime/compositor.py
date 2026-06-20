from __future__ import annotations

import numpy as np

from nanoleaf_sync.color.hdr import _linear_to_srgb_encoded
from nanoleaf_sync.runtime.srgb import (
    linear01_to_srgb_float,
    srgb_encoded_float_to_linear01,
    srgb_u8_to_linear01,
)

_SDR_REFERENCE_NITS = 80.0
_SDR_UNDO_KNEE_LOW = 0.18
_SDR_UNDO_KNEE_HIGH = 0.45


def _luminance_adaptive_undo_ratio(linear_y: np.ndarray) -> np.ndarray:
    edge0 = np.full_like(linear_y, _SDR_UNDO_KNEE_LOW, dtype=np.float32)
    edge1 = np.full_like(linear_y, _SDR_UNDO_KNEE_HIGH, dtype=np.float32)
    width = np.maximum(edge1 - edge0, 1e-6)
    t = np.clip((linear_y - edge0) / width, 0.0, 1.0)
    return (1.0 - (t * t * (3.0 - (2.0 * t)))).astype(np.float32, copy=False)


def zone_sdr_boost_undo_ratio(
    zones: np.ndarray,
    *,
    sdr_boost_nits: float,
) -> np.ndarray:
    boost = effective_sdr_boost(sdr_boost_nits=sdr_boost_nits)
    if boost <= 1.0:
        return np.zeros(int(np.asarray(zones).shape[0]), dtype=np.float32)
    linear = srgb_encoded_float_to_linear01(np.asarray(zones, dtype=np.float32))
    y = np.clip(
        (0.2126 * linear[:, 0]) + (0.7152 * linear[:, 1]) + (0.0722 * linear[:, 2]),
        0.0,
        1.0,
    )
    return _luminance_adaptive_undo_ratio(y)


def effective_sdr_boost(*, sdr_boost_nits: float) -> float:
    """Return the linear SDR boost scalar relative to the KDE SDR reference."""

    return max(0.0, float(sdr_boost_nits)) / _SDR_REFERENCE_NITS


def apply_sdr_boost_compensation(
    frame: np.ndarray,
    *,
    sdr_boost_nits: float,
    hdr_max_nits: float,
) -> np.ndarray:
    """Apply KDE SDR-on-HDR brightness compensation in linear light (full frame).

    Prefer :func:`apply_zone_sdr_boost` in the 3-stage pipeline where zone
    colours are already available, avoiding an extra full-frame round-trip.
    """

    if frame.dtype != np.uint8:
        frame = np.clip(np.rint(frame), 0.0, 255.0).astype(np.uint8, copy=False)

    boost = effective_sdr_boost(sdr_boost_nits=sdr_boost_nits)
    if boost <= 1.0:
        return frame

    linear = srgb_u8_to_linear01(frame)
    # Undo the SDR-on-HDR brightness boost by dividing, then clamp to [0, 1].
    compensated = np.clip(linear / boost, 0.0, 1.0)
    srgb = _linear_to_srgb_encoded(compensated)
    return np.clip(np.rint(srgb * 255.0), 0.0, 255.0).astype(np.uint8, copy=False)


def apply_zone_sdr_boost_float(
    zones: np.ndarray,
    *,
    sdr_boost_nits: float,
    hdr_max_nits: float,
) -> np.ndarray:
    boost = effective_sdr_boost(sdr_boost_nits=sdr_boost_nits)
    zones_f = np.asarray(zones, dtype=np.float32)
    if boost <= 1.0:
        return zones_f
    linear = srgb_encoded_float_to_linear01(zones_f)
    y = np.clip(
        (0.2126 * linear[:, 0]) + (0.7152 * linear[:, 1]) + (0.0722 * linear[:, 2]),
        0.0,
        1.0,
    )
    undo = _luminance_adaptive_undo_ratio(y)
    divisor = 1.0 + ((boost - 1.0) * undo[:, None])
    compensated = np.clip(linear / divisor, 0.0, 1.0)
    return linear01_to_srgb_float(compensated)


def apply_zone_sdr_boost(
    zones: np.ndarray,
    *,
    sdr_boost_nits: float,
    hdr_max_nits: float,
) -> np.ndarray:
    """Apply KDE SDR-on-HDR brightness compensation on ``(N,3)`` zone colours.

    Operates on already-sampled zone colours instead of the full-resolution
    frame, avoiding an expensive full-frame sRGB ↔ linear round-trip.
    """

    if zones.dtype != np.uint8:
        zones = np.clip(np.rint(zones), 0.0, 255.0).astype(np.uint8, copy=False)

    boost = effective_sdr_boost(sdr_boost_nits=sdr_boost_nits)
    if boost <= 1.0:
        return zones

    # (N,3) uint8 → linear01 → divide → srgb → uint8
    linear = srgb_u8_to_linear01(zones)
    compensated = np.clip(linear / boost, 0.0, 1.0)
    srgb = _linear_to_srgb_encoded(compensated)
    return np.clip(np.rint(srgb * 255.0), 0.0, 255.0).astype(np.uint8, copy=False)
