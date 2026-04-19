from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np
from nanoleaf_sync.runtime.srgb import linear01_to_srgb_u8, srgb_u8_to_linear01


RGBTuple = Tuple[int, int, int]
ZoneRect = Tuple[int, int, int, int]

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


def _ensure_rgb_u8(image: np.ndarray) -> np.ndarray:
    """
    Ensure `image` is an RGB uint8 array.

    The rest of this module assumes:
    - shape: (H, W, 3)
    - dtype: uint8
    """

    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"Expected image shape (H, W, 3), got {image.shape}")
    if image.dtype != np.uint8:
        # Use a copy since the dtype conversion changes values.
        return image.astype(np.uint8, copy=False)
    return image


def average_color(image: np.ndarray) -> RGBTuple:
    """
    Return the average RGB color for the entire image.
    """

    img = _ensure_rgb_u8(image)
    # Compute in float for numerical stability; output int channels.
    mean = img.mean(axis=(0, 1))
    r, g, b = mean.tolist()
    return int(r), int(g), int(b)


def _linear_srgb_to_oklab(linear_rgb: np.ndarray) -> np.ndarray:
    lms = linear_rgb @ _M1.T
    lms_cbrt = np.cbrt(np.clip(lms, 0.0, None))
    return lms_cbrt @ _M2.T


def _oklab_to_linear_srgb(oklab: np.ndarray) -> np.ndarray:
    lms_cbrt = oklab @ _M2_INV.T
    lms = lms_cbrt * lms_cbrt * lms_cbrt
    return lms @ _M1_INV.T


def zone_colors(
    image: np.ndarray,
    zones: Sequence[ZoneRect],
    *,
    sample_step: int = 1,
) -> List[RGBTuple]:
    zone_arr = zone_colors_array(image, zones, sample_step=sample_step)
    return [tuple(int(c) for c in row) for row in zone_arr]


def zone_colors_array(
    image: np.ndarray,
    zones: Sequence[ZoneRect],
    *,
    sample_step: int = 1,
    mode: str = "balanced",
    previous_zone_colors: Sequence[RGBTuple] | None = None,
) -> np.ndarray:
    """
    Given a list of screen regions and an image, return average RGB per zone.

    zones: list of (x, y, width, height) in pixel coordinates.
    """

    img = _ensure_rgb_u8(image)
    h, w, _ = img.shape

    if not zones:
        return np.zeros((0, 3), dtype=np.uint8)

    step = max(1, int(sample_step))

    zones_arr = np.asarray(zones, dtype=np.intp)
    x = zones_arr[:, 0]
    y = zones_arr[:, 1]
    zw = zones_arr[:, 2]
    zh = zones_arr[:, 3]

    if step > 1:
        # Sample a strided working image and map zone coordinates into that space.
        img = img[::step, ::step, :]
        h, w, _ = img.shape
        x = x // step
        y = y // step
        # Ceil-div to preserve minimally-sized zones after downsampling.
        zw = (zw + (step - 1)) // step
        zh = (zh + (step - 1)) // step

    x0 = np.clip(x, 0, w)
    y0 = np.clip(y, 0, h)
    x1 = np.clip(x0 + zw, 0, w)
    y1 = np.clip(y0 + zh, 0, h)

    areas = (x1 - x0) * (y1 - y0)

    linear_rgb = srgb_u8_to_linear01(img)
    oklab = _linear_srgb_to_oklab(linear_rgb)

    # Build per-channel integral image to compute zone sums in O(1) each.
    integral = np.zeros((h + 1, w + 1, 3), dtype=np.float32)
    integral[1:, 1:, :] = oklab.cumsum(axis=0, dtype=np.float32).cumsum(axis=1, dtype=np.float32)

    sums = (
        integral[y1, x1]
        - integral[y0, x1]
        - integral[y1, x0]
        + integral[y0, x0]
    )

    means = np.zeros((len(zones), 3), dtype=np.uint8)
    valid = areas > 0
    if valid.any():
        avg_oklab = (sums[valid] / areas[valid, None]).astype(np.float32, copy=False)
        avg_linear_rgb = _oklab_to_linear_srgb(avg_oklab)
        means[valid] = linear01_to_srgb_u8(avg_linear_rgb)

    if str(mode).strip().lower() != "dynamic":
        return means

    out = means.astype(np.float32)
    prev = (
        np.asarray(previous_zone_colors, dtype=np.float32)
        if previous_zone_colors
        else None
    )
    for idx in range(len(zones)):
        if not valid[idx]:
            continue
        patch = img[y0[idx]:y1[idx], x0[idx]:x1[idx]]
        if patch.size == 0:
            continue
        patch_f = patch.astype(np.float32)
        max_c = patch_f.max(axis=2)
        min_c = patch_f.min(axis=2)
        sat = (max_c - min_c) / np.clip(max_c, 1.0, None)
        lum = (0.2126 * patch_f[:, :, 0]) + (0.7152 * patch_f[:, :, 1]) + (0.0722 * patch_f[:, :, 2])
        contrast = np.clip(float(np.std(lum) / 64.0), 0.0, 1.0)
        zone_lum = float(np.mean(lum))
        zone_lum_norm = np.clip(zone_lum / 255.0, 0.0, 1.0)
        required_delta = 10.0 + (55.0 * zone_lum_norm)
        prominence = np.clip((lum - zone_lum) / required_delta, 0.0, 1.0)
        prominence = np.power(prominence, 1.0 + (1.2 * zone_lum_norm))
        vivid_weight = (
            0.35 + 0.45 * sat + 0.20 * np.clip((lum / 255.0) ** 0.7, 0.0, 1.0)
        ) * prominence
        vivid_flat = vivid_weight.reshape(-1)
        patch_flat = patch_f.reshape(-1, 3)
        if patch_flat.size == 0:
            highlight = np.zeros(3, dtype=np.float32)
        else:
            weight_sum = float(vivid_flat.sum())
            if weight_sum <= 0.0:
                highlight = patch_flat.mean(axis=0)
            else:
                highlight = np.average(patch_flat, axis=0, weights=vivid_flat)

        motion_boost = 0.0
        if prev is not None and idx < len(prev):
            motion = np.abs(out[idx] - prev[idx]).mean() / 255.0
            motion_boost = float(np.clip(motion * 1.8, 0.0, 1.0))

        standout = float(np.clip(np.mean(prominence), 0.0, 1.0))
        highlight_mix = np.clip(
            0.12 + (0.33 * contrast) + (0.30 * motion_boost) + (0.25 * standout),
            0.08,
            0.72,
        )
        candidate = ((1.0 - highlight_mix) * out[idx]) + (highlight_mix * highlight)
        if prev is not None and idx < len(prev):
            max_step = 55.0 + (85.0 * motion_boost)
            delta = np.clip(candidate - prev[idx], -max_step, max_step)
            candidate = prev[idx] + delta
            candidate = (0.70 * prev[idx]) + (0.30 * candidate)
        out[idx] = np.clip(candidate, 0.0, 255.0)

    return np.clip(np.rint(out), 0.0, 255.0).astype(np.uint8)
