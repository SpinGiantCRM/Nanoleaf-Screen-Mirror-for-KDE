from __future__ import annotations

"""
HDR-aware color conversion utilities.

Goal:
- Convert HDR-capable capture buffers into device-ready `sRGB uint8`.
- Keep conversions explicit and metadata-driven so that once the DRM/KMS
  backend exposes transfer/primaries/max-nits, the conversion path can be
  correct without changing downstream logic.
"""

from dataclasses import dataclass
from typing import Any, Literal, Optional, Tuple

import numpy as np


TransferFn = Literal["srgb", "pq", "hlg", "linear", "unknown"]
Primaries = Literal["bt709", "bt2020", "unknown"]

_XYZ_TO_SRGB = np.array(
    [
        [3.2404542, -1.5371385, -0.4985314],
        [-0.9692660, 1.8760108, 0.0415560],
        [0.0556434, -0.2040259, 1.0572252],
    ],
    dtype=np.float32,
)
_BT709_TO_XYZ = np.array(
    [
        [0.4123908, 0.3575843, 0.1804808],
        [0.2126390, 0.7151687, 0.0721923],
        [0.0193308, 0.1191948, 0.9505322],
    ],
    dtype=np.float32,
)
_BT2020_TO_XYZ = np.array(
    [
        [0.6369580, 0.1446169, 0.1688809],
        [0.2627002, 0.6779981, 0.0593017],
        [0.0000000, 0.0280727, 1.0609851],
    ],
    dtype=np.float32,
)
_LINEAR_BT709_TO_SRGB = _XYZ_TO_SRGB @ _BT709_TO_XYZ
_LINEAR_BT2020_TO_SRGB = _XYZ_TO_SRGB @ _BT2020_TO_XYZ


@dataclass(frozen=True)
class HDRMetadata:
    # Transfer function / EOTF for the encoded input.
    transfer: TransferFn = "srgb"
    # Color primaries for the encoded RGB.
    primaries: Primaries = "bt709"
    # Display peak luminance in cd/m^2 (used for tone mapping scaling).
    # Many PQ signals are defined over a 10,000 nit reference; this value
    # helps scale for content/mastering display metadata.
    max_nits: float = 1000.0

    # Some capture backends may report an "encoded range" (0..1 for normalized).
    # We assume normalized float conversion already happens in the caller.

    @staticmethod
    def from_any(value: Any) -> "HDRMetadata":
        if isinstance(value, HDRMetadata):
            return value
        if isinstance(value, dict):
            return HDRMetadata(
                transfer=str(value.get("transfer", HDRMetadata.transfer)),
                primaries=str(value.get("primaries", HDRMetadata.primaries)),
                max_nits=float(value.get("max_nits", HDRMetadata.max_nits)),
            )
        return HDRMetadata()


def _to_float01(rgb: np.ndarray) -> np.ndarray:
    if rgb.dtype == np.uint8:
        return rgb.astype(np.float32, copy=False) / 255.0
    if rgb.dtype == np.uint16:
        return rgb.astype(np.float32, copy=False) / 65535.0
    if np.issubdtype(rgb.dtype, np.floating):
        # Assume already normalized or already close enough; clamp defensively.
        return np.clip(rgb.astype(np.float32, copy=False), 0.0, 1.0)
    # Fallback: interpret as 8-bit.
    return rgb.astype(np.float32, copy=False) / 255.0


def _srgb_eotf_to_linear(c: np.ndarray) -> np.ndarray:
    # c is sRGB-encoded in [0, 1]
    a = 0.055
    threshold = 0.04045
    below = c <= threshold
    out = np.empty_like(c, dtype=np.float32)
    out[below] = c[below] / 12.92
    out[~below] = np.power((c[~below] + a) / (1.0 + a), 2.4)
    return out


def _pq_eotf_to_linear(c: np.ndarray) -> np.ndarray:
    # ST2084 inverse EOTF.
    # c in [0, 1] encoded domain.
    m1 = 0.1593017578125
    m2 = 78.84375
    c1 = 0.8359375
    c2 = 18.8515625
    c3 = 18.6875

    c = np.clip(c, 0.0, 1.0).astype(np.float32, copy=False)
    # L' in reference space scaled by 10000 nits.
    vp = np.power(c, 1.0 / m2)
    num = np.maximum(vp - c1, 0.0)
    den = np.maximum(c2 - c3 * vp, 1e-10)
    l = np.power(np.maximum(num / den, 0.0), 1.0 / m1)
    return l


def _hlg_eotf_to_linear(c: np.ndarray) -> np.ndarray:
    # ITU-R BT.2100 HLG inverse EOTF.
    a = 0.17883277
    b = 1.0 - 4.0 * a
    c0 = 0.5 - a * np.log(4.0 * a)

    c = np.clip(c, 0.0, 1.0).astype(np.float32, copy=False)
    out = np.empty_like(c, dtype=np.float32)
    is_low = c <= 0.5
    out[is_low] = (c[is_low] * c[is_low]) / 3.0
    # exp form for the high range
    out[~is_low] = (np.exp((c[~is_low] - c0) / a) + b) / 12.0
    return out


def _apply_tonemap_reinhard(linear: np.ndarray, max_nits: float) -> np.ndarray:
    # Scale by max_nits to approximate scene luminance.
    # `linear` from our EOTF is normalized relative to reference.
    # This tonemap is intentionally simple; a future iteration can
    # use proper Dolby/BT.2390 tone mapping once you have mastering metadata.
    scale = max(1.0, float(max_nits)) / 100.0
    x = linear * scale
    # Reinhard tone mapping into [0,1)
    return x / (1.0 + x)


def _linear_bt709_to_linear_srgb(linear_rgb: np.ndarray) -> np.ndarray:
    # BT.709 primaries -> linear sRGB (D65)
    return _LINEAR_BT709_TO_SRGB @ linear_rgb.reshape(-1, 3).T


def _linear_bt2020_to_linear_srgb(linear_rgb: np.ndarray) -> np.ndarray:
    # BT.2020 primaries -> linear sRGB (D65)
    return _LINEAR_BT2020_TO_SRGB @ linear_rgb.reshape(-1, 3).T


def _linear_to_srgb_encoded(linear: np.ndarray) -> np.ndarray:
    # linear is in [0, +inf), RGB channel-wise.
    linear = np.clip(linear, 0.0, None)
    a = 0.055
    threshold = 0.0031308
    out = np.empty_like(linear, dtype=np.float32)
    is_low = linear <= threshold
    out[is_low] = linear[is_low] * 12.92
    out[~is_low] = (1.0 + a) * np.power(linear[~is_low], 1.0 / 2.4) - a
    return out


def convert_frame_to_srgb8(
    rgb: np.ndarray,
    metadata: Optional[Any] = None,
) -> np.ndarray:
    """
    Convert a capture RGB buffer into `uint8` sRGB.

    Parameters:
    - rgb: numpy array shaped (H, W, 3). Supported dtypes:
      - uint8 / uint16 / float (assumed normalized).
    - metadata: HDRMetadata or dict with keys:
      - transfer: 'srgb'|'pq'|'hlg'|'linear'
      - primaries: 'bt709'|'bt2020'
      - max_nits: float

    Returns:
    - uint8 RGB array (H, W, 3) suitable for zone averaging + USB packing.
    """

    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"Expected rgb shape (H,W,3); got {rgb.shape}")

    meta = HDRMetadata.from_any(metadata)
    if rgb.dtype == np.uint8 and meta.transfer == "srgb" and meta.primaries == "bt709":
        return rgb
    if (
        np.issubdtype(rgb.dtype, np.floating)
        and meta.transfer == "srgb"
        and meta.primaries == "bt709"
    ):
        return np.clip(np.rint(np.clip(rgb, 0.0, 1.0) * 255.0), 0, 255).astype(np.uint8)

    enc = _to_float01(rgb)

    # Step 1: EOTF (encoded -> linear light)
    if meta.transfer == "srgb":
        linear = _srgb_eotf_to_linear(enc)
    elif meta.transfer == "pq":
        linear = _pq_eotf_to_linear(enc)
    elif meta.transfer == "hlg":
        linear = _hlg_eotf_to_linear(enc)
    elif meta.transfer == "linear":
        linear = enc
    else:
        # Unknown: assume sRGB to preserve decent behavior.
        linear = _srgb_eotf_to_linear(enc)

    # Step 2: Gamut / primaries conversion (linear primaries -> linear sRGB)
    if meta.primaries == "bt709":
        # returns a 3xN matrix; then reshape
        linear_srgb_T = _linear_bt709_to_linear_srgb(linear)
    elif meta.primaries == "bt2020":
        linear_srgb_T = _linear_bt2020_to_linear_srgb(linear)
    else:
        # Unknown primaries: assume already sRGB
        linear_srgb_T = linear.reshape(-1, 3).T

    # linear_srgb_T: (3, N). Reshape back.
    linear_srgb = linear_srgb_T.T.reshape(rgb.shape[0], rgb.shape[1], 3)

    # Step 3: Tone-map into SDR-ish range, then sRGB encode.
    # (Nanoleaf HID expects 8-bit sRGB-like payloads.)
    ldr = _apply_tonemap_reinhard(linear_srgb, max_nits=meta.max_nits)
    srgb = _linear_to_srgb_encoded(ldr)

    srgb_u8 = np.clip(np.rint(srgb * 255.0), 0, 255).astype(np.uint8)
    return srgb_u8
