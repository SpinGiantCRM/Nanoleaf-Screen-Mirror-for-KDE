from __future__ import annotations

import math
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from nanoleaf_sync.capture._utils import zone_box_average
from nanoleaf_sync.color._types import RGBTuple
from nanoleaf_sync.config.model import PrivacyZone
from nanoleaf_sync.config.presets import SAMPLING_MODE_WAVELET_EDGE, edge_locality_profile
from nanoleaf_sync.runtime.novel_features import wavelet_sampling_enabled
from nanoleaf_sync.runtime.palette_adaptive import (
    palette_adaptive_zone_color,
    palette_adaptive_zone_frame,
)
from nanoleaf_sync.runtime.palette_temporal import ZonePaletteTemporalState
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
    if touches_top:
        return "top"
    if touches_bottom:
        return "bottom"
    if touches_left:
        return "left"
    if touches_right:
        return "right"
    return None


def _sigmoid(x: float) -> float:
    if x >= 0.0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _sample_zone_wavelet(
    patch: np.ndarray,
    orientation: str | None,
    *,
    k: float = 8.0,
    threshold: float = 0.35,
    epsilon: float = 1e-3,
) -> np.ndarray:
    if patch.size == 0:
        return np.zeros(3, dtype=np.uint8)
    patch_f = patch.astype(np.float32)
    h, w, _ = patch_f.shape
    strip_avgs: list[np.ndarray] = []
    strip_details: list[np.ndarray] = []
    if orientation in {"left", "right"}:
        n_strips = max(1, w)
        for col in range(n_strips):
            strip = patch_f[:, col : col + 1, :]
            strip_avgs.append(strip.mean(axis=(0, 1)))
            strip_details.append(strip.max(axis=(0, 1)) - strip.min(axis=(0, 1)))
    else:
        n_strips = max(1, h)
        for row in range(n_strips):
            strip = patch_f[row : row + 1, :, :]
            strip_avgs.append(strip.mean(axis=(0, 1)))
            strip_details.append(strip.max(axis=(0, 1)) - strip.min(axis=(0, 1)))
    avg = np.mean(np.stack(strip_avgs, axis=0), axis=0)
    detail = np.mean(np.stack(strip_details, axis=0), axis=0)
    edge_energy = float(np.max(detail) / (float(np.max(avg)) + epsilon))
    blend = _sigmoid(k * (edge_energy - threshold))
    output = avg + blend * (detail - avg)
    return np.clip(np.rint(output), 0.0, 255.0).astype(np.uint8)


@lru_cache(maxsize=256)
def _outer_edge_weight_template(*, zone_h: int, zone_w: int, orientation: str) -> np.ndarray:
    edge_extent = zone_h if orientation in {"top", "bottom"} else zone_w
    depth = min(8, max(2, int(np.ceil(float(edge_extent) * 0.35))), edge_extent)
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


def compute_adaptive_step(
    prev_zone_variance: np.ndarray | None,
    *,
    base_step: int = 1,
    min_step: int = 1,
    max_step: int = 8,
) -> int:
    if prev_zone_variance is None or prev_zone_variance.size == 0:
        return max(min_step, int(base_step))
    mean_var = float(np.mean(prev_zone_variance))
    normalized = float(np.clip(mean_var / 2048.0, 0.0, 1.0))
    step = int(round(max_step - (max_step - min_step) * normalized))
    return max(min_step, min(max_step, step))


def multi_moment_zone_color(pixels: np.ndarray) -> tuple[np.ndarray, str]:
    flat = pixels.reshape(-1, 3).astype(np.float32)
    if flat.size == 0:
        return np.zeros(3, dtype=np.uint8), "mean"
    variance = float(np.var(flat, axis=0).mean())
    if variance < 500:
        return flat.mean(axis=0).astype(np.uint8), "mean"

    median_rgb = np.median(flat, axis=0)
    quantized = (flat // 32).clip(0, 7).astype(np.uint8)
    bin_indices = (
        quantized[:, 0].astype(np.uint16) * 64
        + quantized[:, 1].astype(np.uint16) * 8
        + quantized[:, 2].astype(np.uint16)
    )
    counts = np.bincount(bin_indices, minlength=512)
    dominant_bin = int(counts.argmax())
    dominant_rgb = np.array(
        [
            (dominant_bin // 64) * 32 + 16,
            ((dominant_bin // 8) % 8) * 32 + 16,
            (dominant_bin % 8) * 32 + 16,
        ],
        dtype=np.uint8,
    )
    peak_fraction = float(counts.max() / max(1, len(bin_indices)))
    if peak_fraction > 0.15 and variance > 1000:
        return dominant_rgb, "dominant"
    if variance > 1500:
        return median_rgb.astype(np.uint8), "median"
    return flat.mean(axis=0).astype(np.uint8), "mean"


def edge_anchored_rect(
    zone: ZoneRect,
    frame_w: int,
    frame_h: int,
    *,
    padding_ratio: float = 0.3,
) -> ZoneRect:
    x, y, w, h = (int(zone[0]), int(zone[1]), int(zone[2]), int(zone[3]))
    pad_w = max(1, int(w * padding_ratio))
    pad_h = max(1, int(h * padding_ratio))
    touches_top = y <= 0
    touches_bottom = y + h >= frame_h
    touches_left = x <= 0
    touches_right = x + w >= frame_w
    if touches_left:
        x = max(0, x - pad_w)
        w = min(frame_w - x, w + pad_w)
    elif touches_right:
        w = min(frame_w - x + pad_w, frame_w - x)
    if touches_top:
        y = max(0, y - pad_h)
        h = min(frame_h - y, h + pad_h)
    elif touches_bottom:
        h = min(frame_h - y + pad_h, frame_h - y)
    return (x, y, w, h)


def _apply_privacy_mask(
    image: np.ndarray,
    privacy_zones: Sequence[PrivacyZone],
) -> np.ndarray:
    if not privacy_zones:
        return image
    masked = image.copy()
    h, w = masked.shape[:2]
    for zone in privacy_zones:
        x0 = int(max(0.0, min(1.0, float(zone.x))) * w)
        y0 = int(max(0.0, min(1.0, float(zone.y))) * h)
        x1 = int(max(0.0, min(1.0, float(zone.x + zone.w))) * w)
        y1 = int(max(0.0, min(1.0, float(zone.y + zone.h))) * h)
        if x1 > x0 and y1 > y0:
            masked[y0:y1, x0:x1, :] = 0
    return masked


def _zone_colors_via_box_filter(
    image: np.ndarray,
    zones: Sequence[ZoneRect],
    *,
    edge_locality: str,
    privacy_zones: Sequence[PrivacyZone] = (),
    use_multi_moment: bool = True,
    edge_anchor: bool = True,
    max_pixels: int = 256,
) -> tuple[np.ndarray, np.ndarray]:
    img = _apply_privacy_mask(_ensure_rgb_u8(image), privacy_zones)
    h, w, _ = img.shape
    means = np.zeros((len(zones), 3), dtype=np.uint8)
    variances = np.zeros(len(zones), dtype=np.float32)
    for idx, zone in enumerate(zones):
        sample_rect = edge_anchored_rect(zone, w, h) if edge_anchor else zone
        patch = img[
            sample_rect[1] : sample_rect[1] + sample_rect[3],
            sample_rect[0] : sample_rect[0] + sample_rect[2],
            :,
        ]
        if patch.size == 0:
            continue
        if use_multi_moment:
            color, _selector = multi_moment_zone_color(patch)
            means[idx] = color
        else:
            means[idx] = zone_box_average(img, sample_rect, max_pixels=max_pixels)
        variances[idx] = float(np.var(patch.reshape(-1, 3).astype(np.float32), axis=0).mean())
    return means, variances


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
    zone_arr = np.asarray(zone_colors_array(image, zones, sample_step=sample_step), dtype=np.uint8)
    return [(int(row[0]), int(row[1]), int(row[2])) for row in zone_arr]


@dataclass(frozen=True)
class ZoneSamplingMeta:
    effective_sample_rects: tuple[ZoneRect, ...]
    per_zone_effective_mode: tuple[str, ...]
    per_zone_mixed_fallback: tuple[bool, ...]
    per_zone_palette_diagnostics: tuple[dict[str, object], ...] = ()
    per_zone_palette_temporal_states: tuple[dict[str, object], ...] = ()
    per_zone_variance: tuple[float, ...] = ()


def detect_zone_patch_mixed_content(patch: np.ndarray) -> bool:
    if patch.size == 0:
        return False
    linear = srgb_u8_to_linear01(np.asarray(patch, dtype=np.uint8))
    patch_f = np.asarray(linear, dtype=np.float32)
    if patch_f.ndim != 3 or patch_f.shape[2] != 3:
        return False
    max_c = patch_f.max(axis=2)
    min_c = patch_f.min(axis=2)
    lum = (0.2126 * patch_f[:, :, 0]) + (0.7152 * patch_f[:, :, 1]) + (0.0722 * patch_f[:, :, 2])
    luma_std = float(np.std(lum))
    if luma_std > 0.042:
        return True
    sat = (max_c - min_c) / np.clip(max_c, 0.0001, None)
    zone_lum = float(np.mean(lum))
    required_delta = 0.003 + (0.038 * zone_lum)
    prominence = np.clip((lum - zone_lum) / required_delta, 0.0, 1.0)
    prominence_coverage = float(np.mean(prominence > 0.5))
    max_sat = float(np.max(sat))
    if prominence_coverage < 0.15 and max_sat > 0.25 and luma_std > 0.017:
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
    valid = dv > 1e-6
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


_LOW_LIGHT_VIVID_PEAK = 0.0144
_LOW_LIGHT_PROFILE_PEAK = 0.021
_LOW_LIGHT_PROFILE_CHROMA = 0.006


def _low_light_patch_mean(patch_u8: np.ndarray) -> np.ndarray:
    linear = srgb_u8_to_linear01(np.asarray(patch_u8, dtype=np.uint8))
    avg_linear = linear.reshape(-1, 3).mean(axis=0)
    return linear01_to_srgb_u8(avg_linear.astype(np.float32, copy=False))


def _patch_peak_and_chroma(patch_u8: np.ndarray) -> tuple[float, float]:
    if patch_u8.size == 0:
        return 0.0, 0.0
    linear = srgb_u8_to_linear01(np.asarray(patch_u8, dtype=np.uint8))
    patch_f = np.asarray(linear, dtype=np.float32)
    peak = float(np.max(patch_f))
    mean_rgb = patch_f.reshape(-1, 3).mean(axis=0)
    chroma = float(np.max(mean_rgb) - np.min(mean_rgb))
    return peak, chroma


def _dark_biased_patch_mean(patch_u8: np.ndarray) -> np.ndarray:
    if patch_u8.size == 0:
        return np.zeros(3, dtype=np.uint8)
    flat_linear = srgb_u8_to_linear01(np.asarray(patch_u8, dtype=np.uint8)).reshape(-1, 3)
    flat_lum = (
        (0.2126 * flat_linear[:, 0]) + (0.7152 * flat_linear[:, 1]) + (0.0722 * flat_linear[:, 2])
    )
    median_lum = float(np.median(flat_lum))
    if median_lum >= 0.0058:
        avg_linear = flat_linear.mean(axis=0)
        return linear01_to_srgb_u8(avg_linear.astype(np.float32, copy=False))
    raw_weights = 1.0 / (1.0 + flat_lum * 100.0)
    weights = raw_weights * raw_weights
    weight_sum = float(np.sum(weights))
    if weight_sum <= 1e-6:
        avg_linear = flat_linear.mean(axis=0)
        return linear01_to_srgb_u8(avg_linear.astype(np.float32, copy=False))
    weighted = np.sum(flat_linear * weights[:, None], axis=0) / weight_sum
    return linear01_to_srgb_u8(weighted.astype(np.float32, copy=False))


def _sampling_meta_from_plan(
    *,
    zones: Sequence[ZoneRect],
    per_zone_modes: list[str],
    per_zone_mixed: list[bool],
    per_zone_palette: list[dict[str, object]] | None = None,
    per_zone_temporal: list[dict[str, object]] | None = None,
) -> ZoneSamplingMeta:
    rects = tuple((int(z[0]), int(z[1]), int(z[2]), int(z[3])) for z in zones)
    palette_rows = tuple(per_zone_palette or ())
    temporal_rows = tuple(per_zone_temporal or ())
    return ZoneSamplingMeta(
        effective_sample_rects=rects,
        per_zone_effective_mode=tuple(per_zone_modes),
        per_zone_mixed_fallback=tuple(per_zone_mixed),
        per_zone_palette_diagnostics=palette_rows,
        per_zone_palette_temporal_states=temporal_rows,
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
    previous_palette_algorithms: Sequence[str] | None = None,
    palette_temporal_states: Sequence[dict[str, object]] | None = None,
    stabilize_palette: bool = True,
    global_scene_cut: bool = False,
    palette_frame_index: int = 0,
    return_meta: bool = False,
    privacy_zones: Sequence[PrivacyZone] = (),
    prev_zone_variance: np.ndarray | None = None,
    use_zone_box_filter: bool = False,
    virtual_oversample: int = 0,
    multi_moment_zone_colors: bool = False,
    edge_anchor_sampling: bool = True,
) -> np.ndarray | tuple[np.ndarray, ZoneSamplingMeta]:
    """
    Given a list of screen regions and an image, return average RGB per zone.

    zones: list of (x, y, width, height) in pixel coordinates.
    """

    if not zones:
        empty = np.zeros((0, 3), dtype=np.uint8)
        if return_meta:
            return empty, ZoneSamplingMeta((), (), ())
        return empty

    normalized_sampling_mode = str(sampling_mode or "area_average").strip().lower()
    if virtual_oversample > len(zones):
        from nanoleaf_sync.runtime.virtual_zones import project_to_physical, virtual_zone_samples

        virtual_colors = virtual_zone_samples(image, virtual_oversample)
        means = project_to_physical(virtual_colors, len(zones))
        if return_meta:
            rects = tuple((int(z[0]), int(z[1]), int(z[2]), int(z[3])) for z in zones)
            return means, ZoneSamplingMeta(rects, ("virtual_oversample",) * len(zones), ())
        return means

    step = compute_adaptive_step(
        prev_zone_variance,
        base_step=max(1, int(sample_step)),
    )
    if (
        use_zone_box_filter
        and normalized_sampling_mode in {"area_average", "auto", "edge_direct"}
        and normalized_sampling_mode not in {"vivid_weighted", "peak_luma", "palette_adaptive"}
    ):
        means, zone_variances = _zone_colors_via_box_filter(
            image,
            zones,
            edge_locality=edge_locality,
            privacy_zones=privacy_zones,
            use_multi_moment=multi_moment_zone_colors,
            edge_anchor=edge_anchor_sampling,
        )
        if return_meta:
            rects = tuple((int(z[0]), int(z[1]), int(z[2]), int(z[3])) for z in zones)
            return means, ZoneSamplingMeta(
                rects,
                ("box_filter",) * len(zones),
                (),
                per_zone_variance=tuple(float(v) for v in zone_variances.tolist()),
            )
        return means

    img = _ensure_rgb_u8(image)
    if privacy_zones:
        img = _apply_privacy_mask(img, privacy_zones)
    h, w, _ = img.shape
    orig_h, orig_w = h, w

    step = max(1, int(step))
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
    per_zone_palette: list[dict[str, object]] = [{} for _ in zones]
    per_zone_temporal: list[dict[str, object]] = [{} for _ in zones]
    temporal_states = [
        ZonePaletteTemporalState.from_dict(dict(row)) for row in (palette_temporal_states or ())
    ]
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
            per_zone_modes = [normalized_sampling_mode] * len(zones)
            per_zone_mixed = [False] * len(zones)
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
        elif normalized_sampling_mode == SAMPLING_MODE_WAVELET_EDGE and wavelet_sampling_enabled():
            per_zone_modes = [SAMPLING_MODE_WAVELET_EDGE] * len(zones)
            per_zone_mixed = [False] * len(zones)
            for idx in range(len(zones)):
                if not valid[idx]:
                    continue
                patch_u8 = img[y0[idx] : y1[idx], x0[idx] : x1[idx]]
                if patch_u8.size == 0:
                    continue
                orientation = _zone_screen_orientation(
                    zone_x0=int(x0[idx]),
                    zone_y0=int(y0[idx]),
                    zone_x1=int(x1[idx]),
                    zone_y1=int(y1[idx]),
                    frame_w=w,
                    frame_h=h,
                )
                try:
                    means[idx] = _sample_zone_wavelet(patch_u8, orientation)
                except Exception:
                    per_zone_modes[idx] = "area_average"
                    per_zone_mixed[idx] = True
        elif normalized_sampling_mode == "palette_adaptive":
            per_zone_modes = [normalized_sampling_mode] * len(zones)
            per_zone_mixed = [False] * len(zones)
            for idx in range(len(zones)):
                if not valid[idx]:
                    continue
                patch_u8 = img[y0[idx] : y1[idx], x0[idx] : x1[idx]]
                if patch_u8.size == 0:
                    continue
                if detect_zone_patch_mixed_content(patch_u8):
                    per_zone_mixed[idx] = True
                    per_zone_modes[idx] = "area_mean"
                    means[idx] = _dark_biased_patch_mean(patch_u8)
                    mean_rgb = means[idx]
                    per_zone_palette[idx] = {
                        "selected_sampling_algorithm": "area_mean",
                        "selected_candidate_rgb": (
                            int(mean_rgb[0]),
                            int(mean_rgb[1]),
                            int(mean_rgb[2]),
                        ),
                        "candidate_confidence": 1.0,
                        "saturated_coverage": 0.0,
                        "neutral_white_coverage": 0.0,
                        "highlight_coverage": 0.0,
                        "dominant_hue_degrees": 0.0,
                        "hue_coherence": 0.0,
                        "rejected_neutral_candidate": False,
                        "fallback_reason": "mixed_content",
                        "final_reason": "mixed_content_area_mean",
                        "switch_reason": "mixed_content",
                    }
                    prev_temporal = temporal_states[idx] if idx < len(temporal_states) else None
                    held = (
                        float(mean_rgb[0]),
                        float(mean_rgb[1]),
                        float(mean_rgb[2]),
                    )
                    per_zone_temporal[idx] = ZonePaletteTemporalState(
                        selected_algorithm="area_mean",
                        selected_rgb=(int(mean_rgb[0]), int(mean_rgb[1]), int(mean_rgb[2])),
                        held_rgb=held,
                        selected_confidence=1.0,
                        dominant_hue_degrees=float(
                            prev_temporal.dominant_hue_degrees if prev_temporal else 0.0
                        ),
                    ).to_dict()
                    continue
                prev_state = temporal_states[idx] if idx < len(temporal_states) else None
                if stabilize_palette:
                    color, palette_diag, new_state, merged = palette_adaptive_zone_color(
                        patch_u8,
                        prev_state=prev_state,
                        global_scene_cut=global_scene_cut,
                        frame_index=palette_frame_index,
                    )
                    per_zone_temporal[idx] = new_state.to_dict()
                    per_zone_palette[idx] = merged
                else:
                    frame = palette_adaptive_zone_frame(patch_u8)
                    color = np.clip(np.rint(frame.current_best_rgb), 0.0, 255.0).astype(np.uint8)
                    palette_diag = frame.diagnostics
                    per_zone_palette[idx] = palette_diag.as_dict()
                    per_zone_temporal[idx] = ZonePaletteTemporalState(
                        selected_algorithm=frame.current_best_algorithm,
                        selected_confidence=frame.current_best_confidence,
                        selected_rgb=palette_diag.selected_candidate_rgb,
                        dominant_hue_degrees=palette_diag.dominant_hue_degrees,
                        held_rgb=(
                            float(color[0]),
                            float(color[1]),
                            float(color[2]),
                        ),
                    ).to_dict()
                means[idx] = color
                per_zone_modes[idx] = palette_diag.selected_sampling_algorithm
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
                per_zone_palette=per_zone_palette,
                per_zone_temporal=per_zone_temporal,
            )
        return means

    profile = _COLOR_MODE_PROFILES.get(normalized_mode)
    if profile is None:
        if return_meta:
            return means, _sampling_meta_from_plan(
                zones=zones,
                per_zone_modes=per_zone_modes,
                per_zone_mixed=per_zone_mixed,
                per_zone_palette=per_zone_palette,
                per_zone_temporal=per_zone_temporal,
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
            per_zone_palette=per_zone_palette,
            per_zone_temporal=per_zone_temporal,
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
    previous_palette_algorithms: Sequence[str] | None = None,
    palette_temporal_states: Sequence[dict[str, object]] | None = None,
    stabilize_palette: bool = True,
    global_scene_cut: bool = False,
    palette_frame_index: int = 0,
    privacy_zones: Sequence[PrivacyZone] = (),
    prev_zone_variance: np.ndarray | None = None,
    use_zone_box_filter: bool = False,
    virtual_oversample: int = 0,
    multi_moment_zone_colors: bool = False,
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
        previous_palette_algorithms=previous_palette_algorithms,
        palette_temporal_states=palette_temporal_states,
        stabilize_palette=stabilize_palette,
        global_scene_cut=global_scene_cut,
        palette_frame_index=palette_frame_index,
        privacy_zones=privacy_zones,
        prev_zone_variance=prev_zone_variance,
        use_zone_box_filter=use_zone_box_filter,
        virtual_oversample=virtual_oversample,
        multi_moment_zone_colors=multi_moment_zone_colors,
        return_meta=True,
    )
    assert isinstance(out, tuple)  # nosec B101
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
    linear_img = srgb_u8_to_linear01(image)
    integral_indices = valid_idx[~np.isin(valid_idx, list(weighted_indices))]
    if integral_indices.size > 0:
        cropped = linear_img[by0:by1, bx0:bx1, :]
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
        avg_linear = (sums / areas[integral_indices, None]).astype(np.float32, copy=False)
        means[integral_indices] = linear01_to_srgb_u8(avg_linear)
    for idx, py0, py1, px0, px1, weights in weight_plans:
        patch = linear_img[py0:py1, px0:px1]
        weighted = np.einsum("hwc,hw->c", patch, weights, dtype=np.float64)
        means[idx] = linear01_to_srgb_u8(weighted.astype(np.float32, copy=False))
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

    def _time(fn: Callable[..., np.ndarray]) -> tuple[float, np.ndarray]:
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
