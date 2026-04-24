from __future__ import annotations

import threading
from typing import List, Sequence, Tuple

import numpy as np
from nanoleaf_sync.runtime.srgb import linear01_to_srgb_u8, srgb_u8_to_linear01
from nanoleaf_sync.config.presets import edge_locality_profile


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
_M1_T = np.ascontiguousarray(_M1.T)
_M2_T = np.ascontiguousarray(_M2.T)
_M1_INV_T = np.ascontiguousarray(_M1_INV.T)
_M2_INV_T = np.ascontiguousarray(_M2_INV.T)

_thread_local = threading.local()


_COLOR_MODE_PROFILES = {
    "default": {
        "base_mix": 0.22,
        "contrast_w": 0.32,
        "motion_w": 0.25,
        "standout_w": 0.20,
        "vivid_sat": 0.45,
        "max_step": 62.0,
        "blend": 0.35,
    },
    "dynamic": {
        "base_mix": 0.22,
        "contrast_w": 0.34,
        "motion_w": 0.32,
        "standout_w": 0.28,
        "vivid_sat": 0.50,
        "max_step": 78.0,
        "blend": 0.38,
    },
    "hyper": {
        "base_mix": 0.28,
        "contrast_w": 0.38,
        "motion_w": 0.36,
        "standout_w": 0.34,
        "vivid_sat": 0.58,
        "max_step": 95.0,
        "blend": 0.42,
    },
}


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
        return np.clip(image, 0.0, 255.0).astype(np.uint8)
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
    lms = linear_rgb @ _M1_T
    lms_cbrt = np.cbrt(np.clip(lms, 0.0, None))
    return lms_cbrt @ _M2_T


def _oklab_to_linear_srgb(oklab: np.ndarray) -> np.ndarray:
    lms_cbrt = oklab @ _M2_INV_T
    lms = lms_cbrt * lms_cbrt * lms_cbrt
    return lms @ _M1_INV_T


def _get_integral_buffer(height: int, width: int) -> np.ndarray:
    shape = (int(height), int(width))
    buffer = getattr(_thread_local, "integral_buffer", None)
    buffer_shape = getattr(_thread_local, "integral_buffer_shape", None)
    if buffer is None or buffer_shape != shape:
        buffer = np.empty((shape[0], shape[1], 3), dtype=np.float64)
        _thread_local.integral_buffer = buffer
        _thread_local.integral_buffer_shape = shape
    return buffer


def _edge_localized_weights(
    *,
    zone_x0: int,
    zone_y0: int,
    zone_x1: int,
    zone_y1: int,
    frame_w: int,
    frame_h: int,
    edge_locality: str,
) -> np.ndarray | None:
    zone_w = max(0, int(zone_x1 - zone_x0))
    zone_h = max(0, int(zone_y1 - zone_y0))
    if zone_w <= 0 or zone_h <= 0:
        return None

    edge_thin_limit_w = max(2.0, frame_w * 0.22)
    edge_thin_limit_h = max(2.0, frame_h * 0.22)
    touches_top = zone_y0 <= 0 and zone_h <= edge_thin_limit_h
    touches_bottom = zone_y1 >= frame_h and zone_h <= edge_thin_limit_h
    touches_left = zone_x0 <= 0 and zone_w <= edge_thin_limit_w
    touches_right = zone_x1 >= frame_w and zone_w <= edge_thin_limit_w
    if (touches_top or touches_bottom) and (zone_w / max(1.0, float(frame_w))) > 0.40:
        return None
    if (touches_left or touches_right) and (zone_h / max(1.0, float(frame_h))) > 0.40:
        return None
    if not (touches_top or touches_bottom or touches_left or touches_right):
        return None

    profile = edge_locality_profile(edge_locality)
    yy, xx = np.indices((zone_h, zone_w), dtype=np.float32)
    if touches_top or touches_bottom:
        u = (xx + 0.5) / max(1.0, float(zone_w))
        segment_center = np.exp(-0.5 * ((u - 0.5) / profile.center_sigma) ** 2)
        if touches_top:
            edge_distance = (yy + 0.5) / max(1.0, float(zone_h))
        else:
            edge_distance = (float(zone_h) - (yy + 0.5)) / max(1.0, float(zone_h))
        edge_bias = np.exp(-profile.edge_bias * np.clip(edge_distance, 0.0, 1.0))
    else:
        u = (yy + 0.5) / max(1.0, float(zone_h))
        segment_center = np.exp(-0.5 * ((u - 0.5) / profile.center_sigma) ** 2)
        if touches_left:
            edge_distance = (xx + 0.5) / max(1.0, float(zone_w))
        else:
            edge_distance = (float(zone_w) - (xx + 0.5)) / max(1.0, float(zone_w))
        edge_bias = np.exp(-profile.edge_bias * np.clip(edge_distance, 0.0, 1.0))

    weights = (segment_center * edge_bias).astype(np.float32, copy=False)
    weight_sum = float(weights.sum())
    if weight_sum <= 1e-6:
        return None
    return weights / weight_sum


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
    edge_locality: str = "balanced",
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

    valid = areas > 0

    sums = np.zeros((len(zones), 3), dtype=np.float64)
    if valid.any():
        bx0 = int(np.min(x0[valid]))
        by0 = int(np.min(y0[valid]))
        bx1 = int(np.max(x1[valid]))
        by1 = int(np.max(y1[valid]))

        cropped = img[by0:by1, bx0:bx1, :]
        linear_rgb = srgb_u8_to_linear01(cropped)
        oklab = _linear_srgb_to_oklab(linear_rgb)

        crop_h, crop_w, _ = cropped.shape
        integral = _get_integral_buffer(crop_h + 1, crop_w + 1)
        integral[0, :, :] = 0.0
        integral[:, 0, :] = 0.0
        integral[1:, 1:, :] = oklab.cumsum(axis=0, dtype=np.float64).cumsum(axis=1, dtype=np.float64)

        cx0 = x0 - bx0
        cy0 = y0 - by0
        cx1 = x1 - bx0
        cy1 = y1 - by0

        valid_idx = np.flatnonzero(valid)
        sums[valid_idx] = (
            integral[cy1[valid_idx], cx1[valid_idx]]
            - integral[cy0[valid_idx], cx1[valid_idx]]
            - integral[cy1[valid_idx], cx0[valid_idx]]
            + integral[cy0[valid_idx], cx0[valid_idx]]
        )

    means = np.zeros((len(zones), 3), dtype=np.uint8)
    if valid.any():
        avg_oklab = (sums[valid] / areas[valid, None]).astype(np.float32, copy=False)
        avg_linear_rgb = _oklab_to_linear_srgb(avg_oklab)
        means[valid] = linear01_to_srgb_u8(avg_linear_rgb)

        valid_idx = np.flatnonzero(valid)
        for idx in valid_idx:
            weights = _edge_localized_weights(
                zone_x0=int(x0[idx]),
                zone_y0=int(y0[idx]),
                zone_x1=int(x1[idx]),
                zone_y1=int(y1[idx]),
                frame_w=w,
                frame_h=h,
                edge_locality=edge_locality,
            )
            if weights is None:
                continue
            patch = img[y0[idx]:y1[idx], x0[idx]:x1[idx]]
            if patch.size == 0:
                continue
            patch_linear = srgb_u8_to_linear01(patch)
            weighted_linear = (patch_linear * weights[:, :, None]).sum(axis=(0, 1), dtype=np.float64)
            means[idx] = linear01_to_srgb_u8(weighted_linear.astype(np.float32, copy=False))

    normalized_mode = str(mode).strip().lower()
    if normalized_mode == "balanced":
        return means

    profile = _COLOR_MODE_PROFILES.get(normalized_mode)
    if profile is None:
        return means

    out = means.astype(np.float32)
    prev = np.asarray(previous_zone_colors, dtype=np.float32) if previous_zone_colors is not None else None
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
        vivid_weight = (0.30 + profile["vivid_sat"] * sat + 0.20 * np.clip((lum / 255.0) ** 0.7, 0.0, 1.0)) * prominence
        # Down-weight huge flat areas so large backgrounds don't fully dominate dynamic/hyper modes.
        area_rejection = 1.0 - (0.18 * np.clip((1.0 - sat), 0.0, 1.0) * np.clip((1.0 - prominence), 0.0, 1.0))
        vivid_flat = (vivid_weight * area_rejection).reshape(-1)
        patch_flat = patch_f.reshape(-1, 3)
        weight_sum = float(vivid_flat.sum())
        highlight = patch_flat.mean(axis=0) if weight_sum <= 0.0 else np.average(patch_flat, axis=0, weights=vivid_flat)

        motion_boost = 0.0
        if prev is not None and idx < len(prev):
            motion = np.abs(out[idx] - prev[idx]).mean() / 255.0
            motion_boost = float(np.clip(motion * 1.8, 0.0, 1.0))

        standout = float(np.clip(np.mean(prominence), 0.0, 1.0))
        highlight_mix = np.clip(
            profile["base_mix"] + (profile["contrast_w"] * contrast) + (profile["motion_w"] * motion_boost) + (profile["standout_w"] * standout),
            0.10,
            0.88 if normalized_mode == "hyper" else 0.78,
        )
        candidate = ((1.0 - highlight_mix) * out[idx]) + (highlight_mix * highlight)
        if prev is not None and idx < len(prev):
            max_step = profile["max_step"] + (90.0 * motion_boost)
            delta = np.clip(candidate - prev[idx], -max_step, max_step)
            candidate = prev[idx] + delta
            candidate = ((1.0 - profile["blend"]) * prev[idx]) + (profile["blend"] * candidate)
        out[idx] = np.clip(candidate, 0.0, 255.0)

    return np.clip(np.rint(out), 0.0, 255.0).astype(np.uint8)
