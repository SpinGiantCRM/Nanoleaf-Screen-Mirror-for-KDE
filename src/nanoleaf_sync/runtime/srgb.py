from __future__ import annotations

import numpy as np

_SRGB_TO_LINEAR_LUT = np.array(
    [
        (v / 255.0) / 12.92
        if (v / 255.0) <= 0.04045
        else np.float_power(((v / 255.0) + 0.055) / 1.055, 2.4)
        for v in range(256)
    ],
    dtype=np.float32,
)


def srgb_eotf_to_linear01(c: np.ndarray) -> np.ndarray:
    """Convert sRGB-encoded floats in [0, 1] to linear-light floats."""
    a = 0.055
    threshold = 0.04045
    below = c <= threshold
    out = np.empty_like(c, dtype=np.float32)
    out[below] = c[below] / 12.92
    out[~below] = np.power((c[~below] + a) / (1.0 + a), 2.4)
    return out


def linear01_to_srgb_encoded(linear: np.ndarray) -> np.ndarray:
    """Convert linear-light floats to sRGB-encoded floats in [0, 1]."""
    linear = np.clip(linear, 0.0, None)
    a = 0.055
    threshold = 0.0031308
    out = np.empty_like(linear, dtype=np.float32)
    is_low = linear <= threshold
    out[is_low] = linear[is_low] * 12.92
    out[~is_low] = (1.0 + a) * np.power(linear[~is_low], 1.0 / 2.4) - a
    return np.clip(out, 0.0, 1.0)


def srgb_u8_to_linear01(rgb: np.ndarray) -> np.ndarray:
    """Convert sRGB values to linear-light floats in [0, 1]."""
    if rgb.dtype == np.uint8:
        return _SRGB_TO_LINEAR_LUT[rgb]
    return srgb_eotf_to_linear01(rgb.astype(np.float32, copy=False) / 255.0)


def linear01_to_srgb_u8(linear: np.ndarray) -> np.ndarray:
    """Convert linear-light floats to uint8 sRGB values."""
    encoded = linear01_to_srgb_encoded(linear)
    return np.clip(np.rint(encoded * 255.0), 0.0, 255.0).astype(np.uint8, copy=False)


def srgb_encoded_float_to_linear01(rgb: np.ndarray) -> np.ndarray:
    encoded = np.clip(np.asarray(rgb, dtype=np.float32), 0.0, 255.0) / 255.0
    return srgb_eotf_to_linear01(encoded)


def linear01_to_srgb_float(linear: np.ndarray) -> np.ndarray:
    encoded = linear01_to_srgb_encoded(linear)
    return (np.clip(encoded, 0.0, 1.0) * 255.0).astype(np.float32, copy=False)
