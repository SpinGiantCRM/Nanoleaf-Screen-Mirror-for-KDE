from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from nanoleaf_sync.color._types import RGBTuple
from nanoleaf_sync.config.presets import edge_locality_profile
from nanoleaf_sync.runtime.srgb import linear01_to_srgb_u8, srgb_u8_to_linear01

ZoneRect = tuple[int, int, int, int]
_WeightPlan = tuple[int, int, int, int, int, np.ndarray]
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
    tuple[_WeightPlan, ...],
]


_thread_local = threading.local()
_AUTO_ENGINE_CACHE: dict[
    tuple[tuple[tuple[int, int, int, int], ...], int, int, int, str, str], str
] = {}


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

    orientation = (
        "top"
        if touches_top
        else "bottom"
        if touches_bottom
        else "left"
        if touches_left
        else "right"
    )
    return _edge_weight_template(
        zone_h=zone_h,
        zone_w=zone_w,
        orientation=orientation,
        locality=str(edge_locality),
    )


@lru_cache(maxsize=256)
def _edge_weight_template(
    *, zone_h: int, zone_w: int, orientation: str, locality: str
) -> np.ndarray | None:
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


def _zone_screen_orientation(
    *,
    zone_x0: int,
    zone_y0: int,
    zone_x1: int,
    zone_y1: int,
    frame_w: int,
    frame_h: int,
) -> str | None:
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
    if touches_top:
        return "top"
    if touches_bottom:
        return "bottom"
    if touches_left:
        return "left"
    if touches_right:
        return "right"
    return None


@lru_cache(maxsize=256)
def _outer_edge_weight_template(*, zone_h: int, zone_w: int, orientation: str) -> np.ndarray:
    depth = min(2, zone_h if orientation in {"top", "bottom"} else zone_w)
    depth = max(1, depth)
    weights = np.zeros((zone_h, zone_w), dtype=np.float32)
    if orientation == "top":
        weights[:depth, :] = 1.0
    elif orientation == "bottom":
        weights[-depth:, :] = 1.0
    elif orientation == "left":
        weights[:, :depth] = 1.0
    else:
        weights[:, -depth:] = 1.0
    weight_sum = float(weights.sum())
    if weight_sum <= 1e-6:
        return np.ones((zone_h, zone_w), dtype=np.float32) / float(zone_h * zone_w)
    return weights / weight_sum


@lru_cache(maxsize=128)
def _cached_sampling_plan(
    zones_key: tuple[tuple[int, int, int, int], ...],
    frame_w: int,
    frame_h: int,
    sample_step: int,
    edge_locality: str,
    sampling_mode: str,
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
        h = max(1, int(round(float(h) / float(step))))
        w = max(1, int(round(float(w) / float(step))))
        x = np.clip(np.rint(x.astype(np.float64) / float(step)).astype(np.intp), 0, w)
        y = np.clip(np.rint(y.astype(np.float64) / float(step)).astype(np.intp), 0, h)
        zw = np.maximum(1, np.ceil(zw.astype(np.float64) / float(step)).astype(np.intp))
        zh = np.maximum(1, np.ceil(zh.astype(np.float64) / float(step)).astype(np.intp))
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

    edge_plans: list[_WeightPlan] = []
    mode = str(sampling_mode or "area_average").strip().lower()
    for idx in valid_idx.tolist():
        orientation = _zone_screen_orientation(
            zone_x0=int(x0[idx]),
            zone_y0=int(y0[idx]),
            zone_x1=int(x1[idx]),
            zone_y1=int(y1[idx]),
            frame_w=w,
            frame_h=h,
        )
        weights: np.ndarray | None = None
        if mode == "edge_direct" and orientation is not None:
            weights = _outer_edge_weight_template(
                zone_h=int(y1[idx] - y0[idx]),
                zone_w=int(x1[idx] - x0[idx]),
                orientation=orientation,
            )
        elif mode == "area_average":
            weights = _edge_localized_weights(
                zone_x0=int(x0[idx]),
                zone_y0=int(y0[idx]),
                zone_x1=int(x1[idx]),
                zone_y1=int(y1[idx]),
                frame_w=w,
                frame_h=h,
                edge_locality=edge_locality,
            )
        if weights is not None:
            edge_plans.append(
                (idx, int(y0[idx]), int(y1[idx]), int(x0[idx]), int(x1[idx]), weights)
            )

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
) -> list[RGBTuple]:
    zone_arr = zone_colors_array(image, zones, sample_step=sample_step)
    return [tuple(int(c) for c in row) for row in zone_arr]


@dataclass(frozen=True)
class ZoneSamplingMeta:
    effective_sample_rects: tuple[ZoneRect, ...]
    per_zone_effective_mode: tuple[str, ...]
    per_zone_mixed_fallback: tuple[bool, ...]


def detect_zone_patch_mixed_content(patch: np.ndarray) -> bool:
    if patch.size == 0:
        return False
    patch_f = np.asarray(patch, dtype=np.float32)
    if patch_f.ndim != 3 or patch_f.shape[2] != 3:
        return False
    max_c = patch_f.max(axis=2)
    min_c = patch_f.min(axis=2)
    lum = (0.2126 * patch_f[:, :, 0]) + (0.7152 * patch_f[:, :, 1]) + (0.0722 * patch_f[:, :, 2])
    luma_std = float(np.std(lum))
    if luma_std > 20.0:
        return True
    sat = (max_c - min_c) / np.clip(max_c, 1.0, None)
    zone_lum = float(np.mean(lum))
    zone_lum_norm = np.clip(zone_lum / 255.0, 0.0, 1.0)
    required_delta = 10.0 + (55.0 * zone_lum_norm)
    prominence = np.clip((lum - zone_lum) / required_delta, 0.0, 1.0)
    prominence_coverage = float(np.mean(prominence > 0.5))
    max_sat = float(np.max(sat))
    if prominence_coverage < 0.15 and max_sat > 0.25 and luma_std > 8.0:
        return True
    sat_mask = sat > 0.2
    if int(np.count_nonzero(sat_mask)) < 8:
        return False
    sat_pixels = patch_f[sat_mask]
    r = sat_pixels[:, 0]
    g = sat_pixels[:, 1]
    b = sat_pixels[:, 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    dv = mx - mn
    valid = dv > 1.0
    if not bool(valid.any()):
        return False
    rv = r[valid]
    gv = g[valid]
    bv = b[valid]
    dvv = dv[valid]
    mxv = mx[valid]
    hue_valid = np.zeros_like(mxv, dtype=np.float32)
    red_dominant = mxv == rv
    green_dominant = (mxv == gv) & ~red_dominant
    blue_dominant = ~red_dominant & ~green_dominant
    if bool(red_dominant.any()):
        hue_valid[red_dominant] = ((gv[red_dominant] - bv[red_dominant]) / dvv[red_dominant]) % 6.0
    if bool(green_dominant.any()):
        hue_valid[green_dominant] = (
            2.0 + ((bv[green_dominant] - rv[green_dominant]) / dvv[green_dominant]) % 6.0
        )
    if bool(blue_dominant.any()):
        hue_valid[blue_dominant] = (
            4.0 + ((rv[blue_dominant] - gv[blue_dominant]) / dvv[blue_dominant]) % 6.0
        )
    hue_valid *= np.pi / 3.0
    sin_h = np.sin(hue_valid)
    cos_h = np.cos(hue_valid)
    mean_sin = float(np.mean(sin_h))
    mean_cos = float(np.mean(cos_h))
    hue_spread = float(np.sqrt((mean_sin * mean_sin) + (mean_cos * mean_cos)))
    return hue_spread < 0.85


_LOW_LIGHT_VIVID_PEAK = 32.0
_LOW_LIGHT_PROFILE_PEAK = 40.0
_LOW_LIGHT_PROFILE_CHROMA = 8.0


def _low_light_patch_mean(patch_u8: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(patch_u8.mean(axis=(0, 1))), 0.0, 255.0).astype(np.uint8)


def _patch_peak_and_chroma(patch_u8: np.ndarray) -> tuple[float, float]:
    if patch_u8.size == 0:
        return 0.0, 0.0
    patch_f = np.asarray(patch_u8, dtype=np.float32)
    peak = float(np.max(patch_f))
    mean_rgb = patch_f.reshape(-1, 3).mean(axis=0)
    chroma = float(np.max(mean_rgb) - np.min(mean_rgb))
    return peak, chroma


def _dark_biased_patch_mean(patch_u8: np.ndarray) -> np.ndarray:
    patch_f = np.asarray(patch_u8, dtype=np.float32)
    if patch_f.size == 0:
        return np.zeros(3, dtype=np.uint8)
    flat_rgb = patch_f.reshape(-1, 3)
    flat_lum = (0.2126 * flat_rgb[:, 0]) + (0.7152 * flat_rgb[:, 1]) + (0.0722 * flat_rgb[:, 2])
    median_lum = float(np.median(flat_lum))
    if median_lum >= 25.0:
        return np.clip(np.rint(flat_rgb.mean(axis=0)), 0.0, 255.0).astype(np.uint8)
    weights = 255.0 - flat_lum
    weight_sum = float(np.sum(weights))
    if weight_sum <= 1e-6:
        return np.clip(np.rint(flat_rgb.mean(axis=0)), 0.0, 255.0).astype(np.uint8)
    weighted = np.sum(flat_rgb * weights[:, None], axis=0) / weight_sum
    return np.clip(np.rint(weighted), 0.0, 255.0).astype(np.uint8)


def _sampling_meta_from_plan(
    *,
    zones: Sequence[ZoneRect],
    per_zone_modes: list[str],
    per_zone_mixed: list[bool],
) -> ZoneSamplingMeta:
    rects = tuple((int(z[0]), int(z[1]), int(z[2]), int(z[3])) for z in zones)
    return ZoneSamplingMeta(
        effective_sample_rects=rects,
        per_zone_effective_mode=tuple(per_zone_modes),
        per_zone_mixed_fallback=tuple(per_zone_mixed),
    )


def zone_colors_array(
    image: np.ndarray,
    zones: Sequence[ZoneRect],
    *,
    sample_step: int = 1,
    mode: str = "balanced",
    previous_zone_colors: Sequence[RGBTuple] | None = None,
    edge_locality: str = "balanced",
    engine: str = "auto",
    sampling_mode: str = "area_average",
    return_meta: bool = False,
) -> np.ndarray | tuple[np.ndarray, ZoneSamplingMeta]:
    """
    Given a list of screen regions and an image, return average RGB per zone.

    zones: list of (x, y, width, height) in pixel coordinates.
    """

    img = _ensure_rgb_u8(image)
    h, w, _ = img.shape
    orig_h, orig_w = h, w

    if not zones:
        empty = np.zeros((0, 3), dtype=np.uint8)
        if return_meta:
            return empty, ZoneSamplingMeta((), (), ())
        return empty

    step = max(1, int(sample_step))
    normalized_sampling_mode = str(sampling_mode or "area_average").strip().lower()
    zones_key = tuple((int(zone[0]), int(zone[1]), int(zone[2]), int(zone[3])) for zone in zones)
    if step > 1:
        img = img[::step, ::step, :]
        h, w, _ = img.shape

    x0, y0, x1, y1, areas, valid_idx, bx0, by0, bx1, by1, weight_plans = _cached_sampling_plan(
        zones_key,
        orig_w,
        orig_h,
        step,
        str(edge_locality),
        normalized_sampling_mode,
    )
    valid = areas > 0
    weighted_indices = {plan[0] for plan in weight_plans}

    means = np.zeros((len(zones), 3), dtype=np.uint8)
    mode_name = normalized_sampling_mode
    per_zone_modes: list[str] = [mode_name] * len(zones)
    per_zone_mixed: list[bool] = [False] * len(zones)
    if valid.any():
        normalized_engine = str(engine or "auto").strip().lower()
        selected_engine = normalized_engine
        if normalized_engine == "auto":
            cache_key = (zones_key, w, h, step, str(edge_locality), normalized_sampling_mode)
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
                    weight_plans=weight_plans,
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
                weight_plans=weight_plans,
                weighted_indices=weighted_indices,
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
                weight_plans=weight_plans,
                weighted_indices=weighted_indices,
            )

        if normalized_sampling_mode in {"vivid_weighted", "peak_luma"}:
            linear_img = srgb_u8_to_linear01(img)
            per_zone_modes: list[str] = [normalized_sampling_mode] * len(zones)
            per_zone_mixed: list[bool] = [False] * len(zones)
            for idx in range(len(zones)):
                if not valid[idx]:
                    continue
                patch_u8 = img[y0[idx] : y1[idx], x0[idx] : x1[idx]]
                patch_linear = linear_img[y0[idx] : y1[idx], x0[idx] : x1[idx]]
                if patch_linear.size == 0:
                    continue
                if detect_zone_patch_mixed_content(patch_u8):
                    per_zone_mixed[idx] = True
                    per_zone_modes[idx] = "area_average"
                    means[idx] = _dark_biased_patch_mean(patch_u8)
                    continue
                patch_peak, _patch_chroma = _patch_peak_and_chroma(patch_u8)
                if patch_peak < _LOW_LIGHT_VIVID_PEAK:
                    per_zone_modes[idx] = "area_average"
                    means[idx] = _low_light_patch_mean(patch_u8)
                    continue
                if normalized_sampling_mode == "peak_luma":
                    means[idx] = _peak_luma_zone_mean(patch_linear)
                else:
                    means[idx] = _vivid_weighted_zone_mean(patch_linear)
    else:
        per_zone_modes = [mode_name] * len(zones)
        per_zone_mixed = [False] * len(zones)

    normalized_mode = str(mode).strip().lower()
    if normalized_mode == "balanced":
        if return_meta:
            return means, _sampling_meta_from_plan(
                zones=zones,
                per_zone_modes=per_zone_modes,
                per_zone_mixed=per_zone_mixed,
            )
        return means

    profile = _COLOR_MODE_PROFILES.get(normalized_mode)
    if profile is None:
        if return_meta:
            return means, _sampling_meta_from_plan(
                zones=zones,
                per_zone_modes=per_zone_modes,
                per_zone_mixed=per_zone_mixed,
            )
        return means

    out = means.astype(np.float32)
    prev = (
        np.asarray(previous_zone_colors, dtype=np.float32)
        if previous_zone_colors is not None
        else None
    )
    for idx in range(len(zones)):
        if not valid[idx]:
            continue
        patch = img[y0[idx] : y1[idx], x0[idx] : x1[idx]]
        if patch.size == 0:
            continue
        patch_peak, patch_chroma = _patch_peak_and_chroma(patch)
        if patch_peak < _LOW_LIGHT_PROFILE_PEAK and patch_chroma < _LOW_LIGHT_PROFILE_CHROMA:
            per_zone_modes[idx] = "area_average"
            out[idx] = _low_light_patch_mean(patch).astype(np.float32)
            continue
        patch_f = patch.astype(np.float32)
        max_c = patch_f.max(axis=2)
        min_c = patch_f.min(axis=2)
        sat = (max_c - min_c) / np.clip(max_c, 1.0, None)
        lum = (
            (0.2126 * patch_f[:, :, 0]) + (0.7152 * patch_f[:, :, 1]) + (0.0722 * patch_f[:, :, 2])
        )
        contrast = np.clip(float(np.std(lum) / 64.0), 0.0, 1.0)
        zone_lum = float(np.mean(lum))
        zone_lum_norm = np.clip(zone_lum / 255.0, 0.0, 1.0)
        required_delta = 10.0 + (55.0 * zone_lum_norm)
        prominence = np.clip((lum - zone_lum) / required_delta, 0.0, 1.0)
        prominence = np.power(prominence, 1.0 + (1.2 * zone_lum_norm))
        vivid_weight = (
            0.30 + profile["vivid_sat"] * sat + 0.20 * np.clip((lum / 255.0) ** 0.7, 0.0, 1.0)
        ) * prominence
        # Down-weight huge flat areas so large backgrounds don't fully dominate dynamic/hyper modes.
        area_rejection = 1.0 - (
            0.18 * np.clip((1.0 - sat), 0.0, 1.0) * np.clip((1.0 - prominence), 0.0, 1.0)
        )
        vivid_flat = (vivid_weight * area_rejection).reshape(-1)
        patch_flat = patch_f.reshape(-1, 3)
        weight_sum = float(vivid_flat.sum())
        highlight = (
            patch_flat.mean(axis=0)
            if weight_sum <= 0.0
            else np.average(patch_flat, axis=0, weights=vivid_flat)
        )

        motion_boost = 0.0
        if prev is not None and idx < len(prev):
            motion = np.abs(out[idx] - prev[idx]).mean() / 255.0
            motion_boost = float(np.clip(motion * 1.8, 0.0, 1.0))

        standout = float(np.clip(np.mean(prominence), 0.0, 1.0))
        highlight_mix = np.clip(
            profile["base_mix"]
            + (profile["contrast_w"] * contrast)
            + (profile["motion_w"] * motion_boost)
            + (profile["standout_w"] * standout),
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

    result = np.clip(np.rint(out), 0.0, 255.0).astype(np.uint8)
    if return_meta:
        return result, _sampling_meta_from_plan(
            zones=zones,
            per_zone_modes=per_zone_modes,
            per_zone_mixed=per_zone_mixed,
        )
    return result


def zone_colors_array_with_meta(
    image: np.ndarray,
    zones: Sequence[ZoneRect],
    *,
    sample_step: int = 1,
    mode: str = "balanced",
    previous_zone_colors: Sequence[RGBTuple] | None = None,
    edge_locality: str = "balanced",
    engine: str = "auto",
    sampling_mode: str = "area_average",
) -> tuple[np.ndarray, ZoneSamplingMeta]:
    out = zone_colors_array(
        image,
        zones,
        sample_step=sample_step,
        mode=mode,
        previous_zone_colors=previous_zone_colors,
        edge_locality=edge_locality,
        engine=engine,
        sampling_mode=sampling_mode,
        return_meta=True,
    )
    assert isinstance(out, tuple)
    return out


def _peak_luma_zone_mean(patch_linear: np.ndarray, *, top_fraction: float = 0.25) -> np.ndarray:
    patch_u8 = linear01_to_srgb_u8(patch_linear.reshape(-1, 3)).reshape(patch_linear.shape)
    lum = (
        (0.2126 * patch_u8[:, :, 0].astype(np.float32))
        + (0.7152 * patch_u8[:, :, 1].astype(np.float32))
        + (0.0722 * patch_u8[:, :, 2].astype(np.float32))
    )
    flat_lum = lum.reshape(-1)
    if flat_lum.size == 0:
        return np.zeros(3, dtype=np.uint8)
    cutoff = float(np.quantile(flat_lum, max(0.0, min(1.0, 1.0 - top_fraction))))
    mask = flat_lum >= cutoff
    if not bool(mask.any()):
        mask = np.ones_like(flat_lum, dtype=bool)
    selected = patch_linear.reshape(-1, 3)[mask]
    avg_linear = selected.mean(axis=0).astype(np.float32, copy=False)
    return linear01_to_srgb_u8(avg_linear)


def _vivid_weighted_zone_mean(patch_linear: np.ndarray, *, vivid_sat: float = 0.35) -> np.ndarray:
    patch_u8 = linear01_to_srgb_u8(patch_linear.reshape(-1, 3)).reshape(patch_linear.shape)
    patch_f = patch_u8.astype(np.float32)
    max_c = patch_f.max(axis=2)
    min_c = patch_f.min(axis=2)
    sat = (max_c - min_c) / np.clip(max_c, 1.0, None)
    lum = (0.2126 * patch_f[:, :, 0]) + (0.7152 * patch_f[:, :, 1]) + (0.0722 * patch_f[:, :, 2])
    zone_lum = float(np.mean(lum))
    zone_lum_norm = np.clip(zone_lum / 255.0, 0.0, 1.0)
    required_delta = 10.0 + (55.0 * zone_lum_norm)
    prominence = np.clip((lum - zone_lum) / required_delta, 0.0, 1.0)
    vivid_weight = (
        0.30 + vivid_sat * sat + 0.20 * np.clip((lum / 255.0) ** 0.7, 0.0, 1.0)
    ) * prominence
    vivid_flat = vivid_weight.reshape(-1)
    patch_flat = patch_linear.reshape(-1, 3)
    weight_sum = float(vivid_flat.sum())
    if weight_sum <= 0.0:
        avg_linear = patch_flat.mean(axis=0)
    else:
        avg_linear = np.average(patch_flat, axis=0, weights=vivid_flat)
    return linear01_to_srgb_u8(avg_linear.astype(np.float32, copy=False))


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
    weight_plans: tuple[_WeightPlan, ...],
    weighted_indices: set[int],
) -> np.ndarray:
    means = np.zeros((len(x0), 3), dtype=np.uint8)
    if not valid.any():
        return means
    integral_indices = valid_idx[~np.isin(valid_idx, list(weighted_indices))]
    if integral_indices.size > 0:
        cropped = image[by0:by1, bx0:bx1].astype(np.float64, copy=False)
        integral = _get_integral_buffer(cropped.shape[0] + 1, cropped.shape[1] + 1)
        integral[0, :, :] = 0.0
        integral[:, 0, :] = 0.0
        cropped_sum = cropped.cumsum(axis=0, dtype=np.float64).cumsum(axis=1, dtype=np.float64)
        integral[1:, 1:, :] = cropped_sum
        cx0 = x0 - bx0
        cy0 = y0 - by0
        cx1 = x1 - bx0
        cy1 = y1 - by0
        sums = (
            integral[cy1[integral_indices], cx1[integral_indices]]
            - integral[cy0[integral_indices], cx1[integral_indices]]
            - integral[cy1[integral_indices], cx0[integral_indices]]
            + integral[cy0[integral_indices], cx0[integral_indices]]
        )
        means[integral_indices] = np.clip(
            np.rint(sums / areas[integral_indices, None]), 0.0, 255.0
        ).astype(np.uint8, copy=False)
    for idx, py0, py1, px0, px1, weights in weight_plans:
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
    weight_plans: tuple[_WeightPlan, ...],
    weighted_indices: set[int],
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
    integral_indices = valid_idx[~np.isin(valid_idx, list(weighted_indices))]
    if integral_indices.size > 0:
        cropped_linear = linear_img[by0:by1, bx0:bx1, :]
        crop_h, crop_w, _ = cropped_linear.shape
        integral = _get_integral_buffer(crop_h + 1, crop_w + 1)
        integral[0, :, :] = 0.0
        integral[:, 0, :] = 0.0
        integral[1:, 1:, :] = cropped_linear.cumsum(axis=0, dtype=np.float64).cumsum(
            axis=1, dtype=np.float64
        )
        cx0 = x0 - bx0
        cy0 = y0 - by0
        cx1 = x1 - bx0
        cy1 = y1 - by0
        sums = (
            integral[cy1[integral_indices], cx1[integral_indices]]
            - integral[cy0[integral_indices], cx1[integral_indices]]
            - integral[cy1[integral_indices], cx0[integral_indices]]
            + integral[cy0[integral_indices], cx0[integral_indices]]
        )
        avg_linear = (sums / areas[integral_indices, None]).astype(np.float32, copy=False)
        means[integral_indices] = linear01_to_srgb_u8(avg_linear)
    for idx, py0, py1, px0, px1, weights in weight_plans:
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
    weight_plans: tuple[_WeightPlan, ...],
) -> str:
    import time

    weighted_indices = {plan[0] for plan in weight_plans}

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
            weight_plans=weight_plans,
            weighted_indices=weighted_indices,
        )
        return (time.perf_counter() - start) * 1000.0, out

    legacy_ms, legacy_out = _time(_zone_means_legacy)
    optimized_ms, optimized_out = _time(_zone_means_optimized)
    max_abs_delta = (
        int(np.max(np.abs(legacy_out.astype(np.int16) - optimized_out.astype(np.int16))))
        if legacy_out.size
        else 0
    )
    if legacy_ms <= optimized_ms:
        return "legacy"
    if max_abs_delta <= 6:
        return "optimized"
    return "legacy"
