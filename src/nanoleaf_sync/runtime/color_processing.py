from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from nanoleaf_sync.runtime.srgb import linear01_to_srgb_u8, srgb_u8_to_linear01

_M1 = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ],
    dtype=np.float32,
)
_M2 = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ],
    dtype=np.float32,
)
_M1_INV = np.array(
    [
        [4.0767416621, -3.3077115913, 0.2309699292],
        [-1.2684380046, 2.6097574011, -0.3413193965],
        [-0.0041960863, -0.7034186147, 1.7076147010],
    ],
    dtype=np.float32,
)
_M2_INV = np.array(
    [
        [1.0, 0.3963377774, 0.2158037573],
        [1.0, -0.1055613458, -0.0638541728],
        [1.0, -0.0894841775, -1.2914855480],
    ],
    dtype=np.float32,
)
_M1_T = np.ascontiguousarray(_M1.T)
_M2_T = np.ascontiguousarray(_M2.T)
_M1_INV_T = np.ascontiguousarray(_M1_INV.T)
_M2_INV_T = np.ascontiguousarray(_M2_INV.T)


@dataclass(frozen=True)
class StyleProfile:
    chroma_boost: float
    chroma_cap_ratio: float
    chroma_compression: float
    neutral_lift: float
    neutral_threshold: float


STYLE_PROFILES = {
    "reference": StyleProfile(1.0, 1.03, 0.08, 0.06, 0.030),
    "natural": StyleProfile(1.0, 1.03, 0.08, 0.06, 0.030),
    "ambient": StyleProfile(1.02, 1.10, 0.10, 0.15, 0.038),
    "vivid": StyleProfile(1.10, 1.28, 0.07, 0.12, 0.036),
    "punchy": StyleProfile(1.20, 1.42, 0.05, 0.14, 0.036),
}


def _linear_to_oklab(linear_rgb: np.ndarray) -> np.ndarray:
    lms = linear_rgb @ _M1_T
    lms_cbrt = np.cbrt(np.clip(lms, 0.0, None))
    return lms_cbrt @ _M2_T


def _oklab_to_linear(oklab: np.ndarray) -> np.ndarray:
    lms_cbrt = oklab @ _M2_INV_T
    lms = lms_cbrt * lms_cbrt * lms_cbrt
    return lms @ _M1_INV_T


def rgb_u8_to_oklch(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    linear = srgb_u8_to_linear01(np.asarray(rgb, dtype=np.uint8))
    oklab = _linear_to_oklab(linear)
    a = oklab[..., 1]
    b = oklab[..., 2]
    c = np.sqrt((a * a) + (b * b))
    h = np.arctan2(b, a)
    return oklab[..., 0], c, h


def oklch_to_rgb_u8(l: np.ndarray, c: np.ndarray, h: np.ndarray) -> np.ndarray:
    a = c * np.cos(h)
    b = c * np.sin(h)
    oklab = np.stack((l, a, b), axis=-1)
    linear = _oklab_to_linear(oklab)
    return linear01_to_srgb_u8(linear)


def apply_color_style_mapping(colors: np.ndarray, *, color_style: str) -> np.ndarray:
    style = STYLE_PROFILES.get(str(color_style).strip().lower(), STYLE_PROFILES["ambient"])
    rgb = np.clip(np.rint(colors), 0.0, 255.0).astype(np.uint8, copy=False)
    l, c, h = rgb_u8_to_oklch(rgb)

    c_boosted = c * style.chroma_boost
    c_capped = np.minimum(c_boosted, c * style.chroma_cap_ratio)
    c_mapped = c_capped / (1.0 + (style.chroma_compression * c_capped))

    neutral_weight = np.clip((style.neutral_threshold - c) / max(style.neutral_threshold, 1e-6), 0.0, 1.0)
    l_mapped = np.clip(l + (neutral_weight * style.neutral_lift * (1.0 - l)), 0.0, 1.0)
    c_mapped = np.where(neutral_weight > 0.85, 0.0, c_mapped)

    return oklch_to_rgb_u8(l_mapped.astype(np.float32), c_mapped.astype(np.float32), h.astype(np.float32))


def color_pipeline_diagnostics(*, input_rgb: Any, output_rgb: Any) -> dict[str, float | bool | tuple[int, int, int]]:
    in_rgb = np.clip(np.rint(np.asarray(input_rgb, dtype=np.float32)), 0.0, 255.0).astype(np.uint8)
    out_rgb = np.clip(np.rint(np.asarray(output_rgb, dtype=np.float32)), 0.0, 255.0).astype(np.uint8)
    l_in, c_in, h_in = rgb_u8_to_oklch(in_rgb[None, :])
    l_out, c_out, h_out = rgb_u8_to_oklch(out_rgb[None, :])
    c_in_v = float(c_in[0])
    c_out_v = float(c_out[0])
    hue_diff = float(np.degrees(np.arctan2(np.sin(h_out[0] - h_in[0]), np.cos(h_out[0] - h_in[0]))))
    neutral_in = c_in_v < 0.015
    neutral_out = c_out_v < 0.015
    return {
        "input_rgb": tuple(int(v) for v in in_rgb.tolist()),
        "output_rgb": tuple(int(v) for v in out_rgb.tolist()),
        "input_lightness": float(l_in[0]),
        "output_lightness": float(l_out[0]),
        "input_chroma": c_in_v,
        "output_chroma": c_out_v,
        "chroma_ratio": float(c_out_v / c_in_v) if c_in_v > 1e-6 else 1.0,
        "hue_difference_degrees": 0.0 if neutral_in else hue_diff,
        "neutral_grey_preserved": bool((not neutral_in) or neutral_out),
    }
