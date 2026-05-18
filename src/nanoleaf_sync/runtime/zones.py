from __future__ import annotations

import threading
from functools import lru_cache
from typing import List, Sequence, Tuple

import numpy as np
from nanoleaf_sync.runtime.srgb import linear01_to_srgb_u8, srgb_u8_to_linear01
from nanoleaf_sync.config.presets import edge_locality_profile
from nanoleaf_sync.color._types import RGBTuple


ZoneRect = Tuple[int, int, int, int]
_ZoneSamplingPlan = tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    int,
    int,
    int,
    int,
    tuple[tuple[int, int, int, int, int, np.ndarray], ...],
]


_thread_local = threading.local()
_AUTO_ENGINE_CACHE: dict[tuple[tuple[tuple[int, int, int, int], ...], int, int, int, str], str] = {}


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

    orientation = "top" if touches_top else "bottom" if touches_bottom else "left" if touches_left else "right"
    return _edge_weight_template(
        zone_h=zone_h,
        zone_w=zone_w,
        orientation=orientation,
        locality=str(edge_locality),
    )


@lru_cache(maxsize=256)
def _edge_weight_template(*, zone_h: int, zone_w: int, orientation: str, locality: str) -> np.ndarray | None:
    profile = edge_locality_profile(locality)
    yy, xx = np.indices((zone_h, zone_w), dtype=np.float32)
    if orientation in {"top", "bottom"}:
        u = (xx + 0.5) / max(1.0, float(zone_w))
        segment_center = np.exp(-0.5 * ((u - 0.5) / profile.center_sigma) ** 2)
        if orientation == "top":
            edge_distance = (yy + 0.5) / max(1.0, float(zone_h))
        else:
            edge_distance = (float(zone_h) - (yy + 0.5)) / max(1.0, float(zone_h))
    else:
        u = (yy + 0.5) / max(1.0, float(zone_h))
        segment_center = np.exp(-0.5 * ((u - 0.5) / profile.center_sigma) ** 2)
        if orientation == "left":
            edge_distance = (xx + 0.5) / max(1.0, float(zone_w))
        else:
            edge_distance = (float(zone_w) - (xx + 0.5)) / max(1.0, float(zone_w))
    edge_bias = np.exp(-profile.edge_bias * np.clip(edge_distance, 0.0, 1.0))
    weights = (segment_center * edge_bias).astype(np.float32, copy=False)
    weight_sum = float(weights.sum())
    if weight_sum <= 1e-6:
        return None
    return weights / weight_sum


@lru_cache(maxsize=128)
def _cached_sampling_plan(
    zones_key: tuple[tuple[int, int, int, int], ...],
    frame_w: int,
    frame_h: int,
    sample_step: int,
    edge_locality: str,
) -> _ZoneSamplingPlan:
    step = max(1, int(sample_step))
    h = int(frame_h)
    w = int(frame_w)
    zones_arr = np.asarray(zones_key, dtype=np.intp)
    x = zones_arr[:, 0]
    y = zones_arr[:, 1]
    zw = zones_arr[:, 2]
    zh = zones_arr[:, 3]
    if step > 1:
        h = max(1, h // step + (1 if (h % step) else 0))
        w = max(1, w // step + (1 if (w % step) else 0))
        x = x // step
        y = y // step
        zw = (zw + (step - 1)) // step
        zh = (zh + (step - 1)) // step
    x0 = np.clip(x, 0, w)
    y0 = np.clip(y, 0, h)
    x1 = np.clip(x0 + zw, 0, w)
    y1 = np.clip(y0 + zh, 0, h)
    areas = (x1 - x0) * (y1 - y0)
    valid = areas > 0
    valid_idx = np.flatnonzero(valid).astype(np.intp, copy=False)

    bx0 = int(np.min(x0[valid])) if valid.any() else 0
    by0 = int(np.min(y0[valid])) if valid.any() else 0
    bx1 = int(np.max(x1[valid])) if valid.any() else 0
    by1 = int(np.max(y1[valid])) if valid.any() else 0

    edge_plans: list[tuple[int, int, int, int, np.ndarray]] = []
    for idx in valid_idx.tolist():
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
        edge_plans.append((idx, int(y0[idx]), int(y1[idx]), int(x0[idx]), int(x1[idx]), weights))

    return (
        x0,
        y0,
        x1,
        y1,
        areas,
        valid_idx,
        bx0,
        by0,
        bx1,
        by1,
        tuple(edge_plans),
    )


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
    engine: str = "auto",
) -> np.ndarray:
    """
    Given a list of screen regions and an image, return average RGB per zone.

    zones: list of (x, y, width, height) in pixel coordinates.
    """

    img = _ensure_rgb_u8(image)
    h, w, _ = img.shape
    orig_h, orig_w = h, w

    if not zones:
        return np.zeros((0, 3), dtype=np.uint8)

    step = max(1, int(sample_step))
    zones_key = tuple(
        (int(zone[0]), int(zone[1]), int(zone[2]), int(zone[3]))
        for zone in zones
    )
    if step > 1:
        img = img[::step, ::step, :]
        h, w, _ = img.shape

    x0, y0, x1, y1, areas, valid_idx, bx0, by0, bx1, by1, edge_plans = _cached_sampling_plan(
        zones_key,
        orig_w,
        orig_h,
        step,
        str(edge_locality),
    )
    valid = areas > 0

    means = np.zeros((len(zones), 3), dtype=np.uint8)
    if valid.any():
        normalized_engine = str(engine or "auto").strip().lower()
        selected_engine = normalized_engine
        if normalized_engine == "auto":
            cache_key = (zones_key, w, h, step, str(edge_locality))
            selected_engine = _AUTO_ENGINE_CACHE.get(cache_key, "")
            if not selected_engine:
                selected_engine = _select_faster_engine_auto(
                    image=img,
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    areas=areas,
                    valid=valid,
                    valid_idx=valid_idx,
                    bx0=bx0,
                    by0=by0,
                    bx1=bx1,
                    by1=by1,
                    edge_plans=edge_plans,
                )
                _AUTO_ENGINE_CACHE[cache_key] = selected_engine
        if selected_engine == "legacy":
            means = _zone_means_legacy(
                image=img,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                areas=areas,
                valid=valid,
                valid_idx=valid_idx,
                bx0=bx0,
                by0=by0,
                bx1=bx1,
                by1=by1,
                edge_plans=edge_plans,
            )
        else:
            means = _zone_means_optimized(
                image=img,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                areas=areas,
                valid=valid,
                valid_idx=valid_idx,
                bx0=bx0,
                by0=by0,
                bx1=bx1,
                by1=by1,
                edge_plans=edge_plans,
            )

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


def _zone_means_legacy(
    *,
    image: np.ndarray,
    x0: np.ndarray,
    y0: np.ndarray,
    x1: np.ndarray,
    y1: np.ndarray,
    areas: np.ndarray,
    valid: np.ndarray,
    valid_idx: np.ndarray,
    bx0: int,
    by0: int,
    bx1: int,
    by1: int,
    edge_plans: tuple[tuple[int, int, int, int, int, np.ndarray], ...],
) -> np.ndarray:
    means = np.zeros((len(x0), 3), dtype=np.uint8)
    if not valid.any():
        return means
    cropped = image[by0:by1, bx0:bx1].astype(np.float64, copy=False)
    integral = _get_integral_buffer(cropped.shape[0] + 1, cropped.shape[1] + 1)
    integral[0, :, :] = 0.0
    integral[:, 0, :] = 0.0
    integral[1:, 1:, :] = cropped.cumsum(axis=0, dtype=np.float64).cumsum(axis=1, dtype=np.float64)
    cx0 = x0 - bx0
    cy0 = y0 - by0
    cx1 = x1 - bx0
    cy1 = y1 - by0
    sums = (
        integral[cy1[valid_idx], cx1[valid_idx]]
        - integral[cy0[valid_idx], cx1[valid_idx]]
        - integral[cy1[valid_idx], cx0[valid_idx]]
        + integral[cy0[valid_idx], cx0[valid_idx]]
    )
    means[valid] = np.clip(np.rint(sums / areas[valid_idx, None]), 0.0, 255.0).astype(np.uint8, copy=False)
    for idx, py0, py1, px0, px1, weights in edge_plans:
        patch = image[py0:py1, px0:px1].astype(np.float64, copy=False)
        weighted = np.einsum("hwc,hw->c", patch, weights, dtype=np.float64)
        means[idx] = np.clip(np.rint(weighted), 0.0, 255.0).astype(np.uint8, copy=False)
    return means


def _zone_means_optimized(
    *,
    image: np.ndarray,
    x0: np.ndarray,
    y0: np.ndarray,
    x1: np.ndarray,
    y1: np.ndarray,
    areas: np.ndarray,
    valid: np.ndarray,
    valid_idx: np.ndarray,
    bx0: int,
    by0: int,
    bx1: int,
    by1: int,
    edge_plans: tuple[tuple[int, int, int, int, int, np.ndarray], ...],
) -> np.ndarray:
    """Zone-average in linear RGB via integral image (no full-frame Oklab pass).

    Zone sampling occurs before any Oklch/Oklab conversion so the per-pixel
    cost of colour-space transforms is avoided on the full-resolution frame.
    Per-zone Oklch mapping is deferred to the downstream color_processing
    pipeline, which only operates on the small per-zone averaged colours.
    """
    means = np.zeros((len(x0), 3), dtype=np.uint8)
    if not valid.any():
        return means
    linear_img = srgb_u8_to_linear01(image)
    cropped_linear = linear_img[by0:by1, bx0:bx1, :]
    crop_h, crop_w, _ = cropped_linear.shape
    integral = _get_integral_buffer(crop_h + 1, crop_w + 1)
    integral[0, :, :] = 0.0
    integral[:, 0, :] = 0.0
    integral[1:, 1:, :] = cropped_linear.cumsum(axis=0, dtype=np.float64).cumsum(axis=1, dtype=np.float64)
    cx0 = x0 - bx0
    cy0 = y0 - by0
    cx1 = x1 - bx0
    cy1 = y1 - by0
    sums = (
        integral[cy1[valid_idx], cx1[valid_idx]]
        - integral[cy0[valid_idx], cx1[valid_idx]]
        - integral[cy1[valid_idx], cx0[valid_idx]]
        + integral[cy0[valid_idx], cx0[valid_idx]]
    )
    avg_linear = (sums / areas[valid_idx, None]).astype(np.float32, copy=False)
    means[valid] = linear01_to_srgb_u8(avg_linear)
    for idx, py0, py1, px0, px1, weights in edge_plans:
        patch_linear = linear_img[py0:py1, px0:px1]
        weighted_linear = np.einsum("hwc,hw->c", patch_linear, weights, dtype=np.float64)
        means[idx] = linear01_to_srgb_u8(weighted_linear.astype(np.float32, copy=False))
    return means


def _select_faster_engine_auto(
    *,
    image: np.ndarray,
    x0: np.ndarray,
    y0: np.ndarray,
    x1: np.ndarray,
    y1: np.ndarray,
    areas: np.ndarray,
    valid: np.ndarray,
    valid_idx: np.ndarray,
    bx0: int,
    by0: int,
    bx1: int,
    by1: int,
    edge_plans: tuple[tuple[int, int, int, int, int, np.ndarray], ...],
) -> str:
    import time

    def _time(fn) -> tuple[float, np.ndarray]:
        start = time.perf_counter()
        out = fn(
            image=image,
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            areas=areas,
            valid=valid,
            valid_idx=valid_idx,
            bx0=bx0,
            by0=by0,
            bx1=bx1,
            by1=by1,
            edge_plans=edge_plans,
        )
        return (time.perf_counter() - start) * 1000.0, out

    legacy_ms, legacy_out = _time(_zone_means_legacy)
    optimized_ms, optimized_out = _time(_zone_means_optimized)
    max_abs_delta = int(np.max(np.abs(legacy_out.astype(np.int16) - optimized_out.astype(np.int16)))) if legacy_out.size else 0
    if legacy_ms <= optimized_ms:
        return "legacy"
    if max_abs_delta <= 6:
        return "optimized"
    return "legacy"
