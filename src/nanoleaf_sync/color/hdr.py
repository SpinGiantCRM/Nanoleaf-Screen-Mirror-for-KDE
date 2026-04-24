"""
HDR-aware color conversion utilities.

Goal:
- Convert HDR-capable capture buffers into device-ready `sRGB uint8`.
- Keep conversions explicit and metadata-driven so that once the DRM/KMS
  backend exposes transfer/primaries/max-nits, the conversion path can be
  correct without changing downstream logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

import numpy as np
from nanoleaf_sync.runtime.srgb import (
    linear01_to_srgb_encoded,
    linear01_to_srgb_u8,
    srgb_eotf_to_linear01,
    srgb_u8_to_linear01,
)


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


def _normalize_metadata_source(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"backend", "backend metadata", "backend-metadata"}:
        return "backend metadata"
    if normalized in {"user", "user preset", "preset"}:
        return "user preset"
    return "unknown"


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


def _srgb_u8_to_linear01(rgb: np.ndarray) -> np.ndarray:
    """Convert uint8 sRGB values to linear-light floats in [0, 1]."""
    return srgb_u8_to_linear01(rgb)


def _linear01_to_srgb_u8(linear: np.ndarray) -> np.ndarray:
    """Convert linear-light floats to uint8 sRGB values."""
    return linear01_to_srgb_u8(linear)


def _srgb_eotf_to_linear(c: np.ndarray) -> np.ndarray:
    return srgb_eotf_to_linear01(c)


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
    linear = np.power(np.maximum(num / den, 0.0), 1.0 / m1)
    return linear


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


def _apply_tonemap_hable(linear: np.ndarray, max_nits: float) -> np.ndarray:
    # Hable / Uncharted 2 filmic curve:
    # better shoulder roll-off and colorfulness retention than Reinhard.
    scale = max(1.0, float(max_nits)) / 100.0
    x = np.clip(linear * scale, 0.0, None).astype(np.float32, copy=False)

    a = 0.15
    b = 0.50
    c = 0.10
    d = 0.20
    e = 0.02
    f = 0.30
    white = 11.2

    def _hable_curve(v: np.ndarray) -> np.ndarray:
        return ((v * (a * v + c * b) + d * e) / (v * (a * v + b) + d * f)) - (e / f)

    white_scale = 1.0 / max(float(_hable_curve(np.array([white], dtype=np.float32))[0]), 1e-6)
    return np.clip(_hable_curve(x) * white_scale, 0.0, 1.0)


def _looks_sdr_encoded(enc: np.ndarray, *, transfer: str) -> bool:
    p99 = float(np.percentile(enc, 99.5))
    if transfer == "pq":
        return p99 < 0.58
    if transfer == "hlg":
        return p99 < 0.70
    return True


def analyze_hdr_path(rgb: np.ndarray, metadata: Optional[Any] = None) -> dict[str, object]:
    meta = HDRMetadata.from_any(metadata)
    source = "unknown"
    if isinstance(metadata, dict):
        source = _normalize_metadata_source(metadata.get("source", "unknown"))
    assumed_transfer = meta.transfer
    assumed_primaries = meta.primaries
    assumption_note = ""
    if meta.transfer not in {"srgb", "pq", "hlg", "linear"}:
        assumed_transfer = "srgb"
        assumption_note = "unknown transfer; assuming sRGB"
    if meta.primaries not in {"bt709", "bt2020"}:
        assumed_primaries = "bt709"
        assumption_note = (assumption_note + "; " if assumption_note else "") + "unknown primaries; assuming BT.709"

    enc = _to_float01(rgb)
    tone_map_planned = assumed_transfer in {"pq", "hlg"}
    if tone_map_planned and _looks_sdr_encoded(enc, transfer=assumed_transfer):
        tone_map_planned = False
        assumption_note = (assumption_note + "; " if assumption_note else "") + "input appears SDR-like; skipping extra HDR tone mapping"
    if assumed_transfer in {"srgb", "linear"}:
        tone_map_planned = False

    return {
        "input_transfer": assumed_transfer,
        "input_primaries": assumed_primaries,
        "metadata_source": source,
        "tone_mapping_applied": bool(tone_map_planned),
        "assumption": assumption_note or "none",
    }


def _linear_bt709_to_linear_srgb(linear_rgb: np.ndarray) -> np.ndarray:
    # BT.709 primaries -> linear sRGB (D65)
    return _LINEAR_BT709_TO_SRGB @ linear_rgb.reshape(-1, 3).T


def _linear_bt2020_to_linear_srgb(linear_rgb: np.ndarray) -> np.ndarray:
    # BT.2020 primaries -> linear sRGB (D65)
    return _LINEAR_BT2020_TO_SRGB @ linear_rgb.reshape(-1, 3).T


def _linear_to_srgb_encoded(linear: np.ndarray) -> np.ndarray:
    return linear01_to_srgb_encoded(linear)


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

    path = analyze_hdr_path(rgb, metadata=metadata)

    # Step 1: EOTF (encoded -> linear light)
    transfer = str(path["input_transfer"])
    if transfer == "srgb":
        linear = _srgb_eotf_to_linear(enc)
    elif transfer == "pq":
        linear = _pq_eotf_to_linear(enc)
    elif transfer == "hlg":
        linear = _hlg_eotf_to_linear(enc)
    elif transfer == "linear":
        linear = enc
    else:
        # Unknown: assume sRGB to preserve decent behavior.
        linear = _srgb_eotf_to_linear(enc)

    # Step 2: Gamut / primaries conversion (linear primaries -> linear sRGB)
    primaries = str(path["input_primaries"])
    if primaries == "bt709":
        # returns a 3xN matrix; then reshape
        linear_srgb_T = _linear_bt709_to_linear_srgb(linear)
    elif primaries == "bt2020":
        linear_srgb_T = _linear_bt2020_to_linear_srgb(linear)
    else:
        # Unknown primaries: assume already sRGB
        linear_srgb_T = linear.reshape(-1, 3).T

    # linear_srgb_T: (3, N). Reshape back.
    linear_srgb = linear_srgb_T.T.reshape(rgb.shape[0], rgb.shape[1], 3)

    # Step 3: Tone-map into SDR-ish range, then sRGB encode.
    # (Nanoleaf HID expects 8-bit sRGB-like payloads.)
    if bool(path["tone_mapping_applied"]):
        ldr = _apply_tonemap_hable(linear_srgb, max_nits=meta.max_nits)
    else:
        ldr = np.clip(linear_srgb, 0.0, 1.0)
    srgb = _linear_to_srgb_encoded(ldr)

    srgb_u8 = np.clip(np.rint(srgb * 255.0), 0, 255).astype(np.uint8)
    return srgb_u8
