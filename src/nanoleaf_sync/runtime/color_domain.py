from __future__ import annotations

from enum import StrEnum

import numpy as np

from nanoleaf_sync.runtime.srgb import (
    linear01_to_srgb_u8,
    srgb_encoded_float_to_linear01,
    srgb_u8_to_linear01,
)


class ColorDomain(StrEnum):
    ENCODED_SRGB_U8 = "encoded_srgb_u8"
    ENCODED_SRGB_FLOAT = "encoded_srgb_float"
    LINEAR_SRGB = "linear_srgb"


def infer_color_domain(colors: np.ndarray) -> ColorDomain:
    raw = np.asarray(colors)
    if raw.size == 0:
        return ColorDomain.ENCODED_SRGB_U8
    if raw.dtype == np.uint8:
        return ColorDomain.ENCODED_SRGB_U8
    rgb = raw.astype(np.float32, copy=False)
    if rgb.size == 0:
        return ColorDomain.ENCODED_SRGB_U8
    peak = float(np.max(rgb))
    if peak <= 1.0:
        return ColorDomain.ENCODED_SRGB_FLOAT
    return ColorDomain.ENCODED_SRGB_U8


def to_linear_srgb(colors: np.ndarray, *, domain: ColorDomain | None = None) -> np.ndarray:
    resolved = domain or infer_color_domain(colors)
    rgb = np.asarray(colors, dtype=np.float32)
    if resolved == ColorDomain.LINEAR_SRGB:
        return np.clip(rgb, 0.0, 1.0)
    if resolved == ColorDomain.ENCODED_SRGB_FLOAT:
        return srgb_encoded_float_to_linear01(np.clip(rgb, 0.0, 1.0))
    u8 = np.clip(np.rint(rgb), 0.0, 255.0).astype(np.uint8, copy=False)
    return srgb_u8_to_linear01(u8)


def from_linear_srgb(linear: np.ndarray) -> np.ndarray:
    return linear01_to_srgb_u8(np.clip(linear, 0.0, 1.0)).astype(np.float32, copy=False)
