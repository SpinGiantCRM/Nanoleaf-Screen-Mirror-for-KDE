from __future__ import annotations

import numpy as np

from nanoleaf_sync.color.hdr import _apply_tonemap_hable, _linear_to_srgb_encoded
from nanoleaf_sync.runtime.srgb import srgb_u8_to_linear01


def apply_sdr_boost_compensation(
    frame: np.ndarray,
    *,
    sdr_boost_nits: float,
    hdr_max_nits: float,
) -> np.ndarray:
    """Apply KDE SDR-on-HDR brightness compensation in linear light."""

    if frame.dtype != np.uint8:
        frame = np.clip(np.rint(frame), 0.0, 255.0).astype(np.uint8, copy=False)

    boost = float(sdr_boost_nits) / 80.0
    if boost <= 1.0:
        return frame

    linear = srgb_u8_to_linear01(frame)
    boosted = np.clip(linear * boost, 0.0, None)
    ldr = _apply_tonemap_hable(boosted, max_nits=float(hdr_max_nits))
    srgb = _linear_to_srgb_encoded(ldr)
    return np.clip(np.rint(srgb * 255.0), 0.0, 255.0).astype(np.uint8, copy=False)
