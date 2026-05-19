from __future__ import annotations

import numpy as np

from nanoleaf_sync.runtime.srgb import srgb_u8_to_linear01
from nanoleaf_sync.color.hdr import _linear_to_srgb_encoded

_SDR_REFERENCE_NITS = 80.0


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
