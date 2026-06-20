from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nanoleaf_sync.runtime.color_processing import oklch_to_rgb_u8, rgb_u8_to_oklch


@dataclass(frozen=True)
class AdaptiveSmoothingDiagnostics:
    scene_activity: str
    median_zone_delta: float
    max_zone_delta: float
    min_effective_alpha: float
    max_effective_alpha: float
    deadband_active: bool


_DARK_ISOLATION_PEAK = 18.0
_BRIGHT_NEIGHBOR_DELTA = 24.0
_LOW_LIGHT_HOLD_PEAK = 35.0
_LOW_LIGHT_NEUTRAL_ISOLATION_PEAK = 40.0


def apply_neighbor_blend(mapped: np.ndarray, *, spread_mode: str) -> np.ndarray:
    mode = str(spread_mode or "balanced").strip().lower()
    weight = {"off": 0.0, "precise": 0.04, "balanced": 0.12, "soft": 0.24}.get(mode, 0.12)
    n = int(mapped.shape[0])
    if n < 8 or weight <= 0.0:
        return mapped

    mapped_f = np.asarray(mapped, dtype=np.float32)
    peaks = np.max(mapped_f, axis=1)
    chroma = peaks - np.min(mapped_f, axis=1)
    low_light_neutral_mask = (peaks < _LOW_LIGHT_NEUTRAL_ISOLATION_PEAK) & (chroma < 6.0)
    dark_mask = (peaks < _DARK_ISOLATION_PEAK) | low_light_neutral_mask
    out = mapped_f.copy()

    prev_neighbor = np.empty_like(mapped_f)
    next_neighbor = np.empty_like(mapped_f)
    prev_neighbor[0] = mapped_f[0]
    prev_neighbor[1:] = mapped_f[:-1]
    next_neighbor[-1] = mapped_f[-1]
    next_neighbor[:-1] = mapped_f[1:]

    prev_peaks = np.empty_like(peaks)
    next_peaks = np.empty_like(peaks)
    prev_peaks[0] = peaks[0]
    prev_peaks[1:] = peaks[:-1]
    next_peaks[-1] = peaks[-1]
    next_peaks[:-1] = peaks[1:]

    prev_w = np.full(n, weight, dtype=np.float32)
    next_w = np.full(n, weight, dtype=np.float32)
    prev_w[0] = 0.0
    next_w[-1] = 0.0
    prev_w = np.where((prev_peaks - peaks) > _BRIGHT_NEIGHBOR_DELTA, 0.0, prev_w)
    next_w = np.where((next_peaks - peaks) > _BRIGHT_NEIGHBOR_DELTA, 0.0, next_w)

    total_w = prev_w + next_w
    blended = (
        (1.0 - total_w)[:, None] * mapped_f
        + prev_w[:, None] * prev_neighbor
        + next_w[:, None] * next_neighbor
    )
    active = ~dark_mask
    return np.where(active[:, None], blended, out)


def _oklab_blend_rows(
    current: np.ndarray,
    previous: np.ndarray,
    alpha: np.ndarray,
) -> np.ndarray:
    cur_u8 = np.clip(np.rint(current), 0.0, 255.0).astype(np.uint8, copy=False)
    prev_u8 = np.clip(np.rint(previous), 0.0, 255.0).astype(np.uint8, copy=False)
    l_c, c_c, h_c = rgb_u8_to_oklch(cur_u8)
    l_p, c_p, h_p = rgb_u8_to_oklch(prev_u8)
    a = np.clip(alpha.astype(np.float32), 0.0, 1.0)
    l_out = (a * l_c) + ((1.0 - a) * l_p)
    c_out = (a * c_c) + ((1.0 - a) * c_p)
    h_delta = np.arctan2(np.sin(h_c - h_p), np.cos(h_c - h_p))
    h_out = h_p + (a * h_delta)
    return oklch_to_rgb_u8(l_out, c_out, h_out).astype(np.float32, copy=False)


def adaptive_one_euro_blend(
    *,
    current: np.ndarray,
    previous: np.ndarray,
    smoothing: float,
    smoothing_speed: float = 0.75,
    motion_preset: str = "responsive",
) -> tuple[np.ndarray, AdaptiveSmoothingDiagnostics]:
    preset = str(motion_preset or "responsive").strip().lower()
    min_alpha = max(0.0, min(1.0, float(smoothing)))
    speed_gain = np.clip(float(smoothing_speed) / 4.0, 0.0, 1.0) ** 2

    delta = current - previous
    zone_delta = np.mean(np.abs(delta), axis=1)
    if zone_delta.size == 0:
        diagnostics = AdaptiveSmoothingDiagnostics(
            scene_activity="static",
            median_zone_delta=0.0,
            max_zone_delta=0.0,
            min_effective_alpha=min_alpha,
            max_effective_alpha=min_alpha,
            deadband_active=False,
        )
        return current, diagnostics

    deadband = 2.0
    tiny_blend = 0.08
    zone_gamma = 1.10
    scene_boost = {
        "static": 0.0,
        "low": 0.22,
        "medium": 0.44,
        "high": 0.70,
    }
    large_jump = 42.0
    jump_alpha_min = 0.72
    if preset == "calm":
        deadband = 3.0
        tiny_blend = 0.03
        zone_gamma = 1.35
        scene_boost = {"static": 0.0, "low": 0.16, "medium": 0.34, "high": 0.56}
        large_jump = 50.0
        jump_alpha_min = 0.58
    elif preset == "dynamic":
        deadband = 1.2
        tiny_blend = 0.14
        zone_gamma = 0.90
        scene_boost = {"static": 0.04, "low": 0.30, "medium": 0.55, "high": 0.84}
        large_jump = 34.0
        jump_alpha_min = 0.84

    median_delta = float(np.median(zone_delta))
    mean_delta = float(np.mean(zone_delta))
    max_delta = float(np.max(zone_delta))

    if median_delta < deadband * 1.15 and mean_delta < deadband * 1.4:
        scene_activity = "static"
    elif median_delta < 9.0:
        scene_activity = "low"
    elif median_delta < 24.0:
        scene_activity = "medium"
    else:
        scene_activity = "high"

    zone_motion = np.clip((zone_delta - deadband) / max(1e-6, 64.0 - deadband), 0.0, 1.0)
    zone_motion = np.power(zone_motion, zone_gamma)
    scene_motion = scene_boost[scene_activity]
    adaptive_motion = np.maximum(zone_motion, scene_motion)
    adaptive_motion *= speed_gain
    alpha_zone = min_alpha + (1.0 - min_alpha) * adaptive_motion

    large_change_mask = zone_delta >= large_jump
    if large_change_mask.any():
        fast_floor = jump_alpha_min * (0.65 + 0.35 * speed_gain)
        alpha_zone = np.where(large_change_mask, np.maximum(alpha_zone, fast_floor), alpha_zone)

    current_peak = np.max(current, axis=1)
    previous_peak = np.max(previous, axis=1)
    chroma_spread = current_peak - np.min(current, axis=1)
    previous_chroma = previous_peak - np.min(previous, axis=1)
    achromatic = chroma_spread < 4.0
    black_cut_mask = (current_peak < 8.0) & (previous_peak > 64.0)
    if black_cut_mask.any():
        alpha_zone = np.where(black_cut_mask, 1.0, alpha_zone)

    dark_release_mask = (current_peak < 20.0) & (
        (previous_peak >= current_peak + 8.0)
        | (
            (previous_chroma >= 4.0)
            & (previous_peak >= 14.0)
            & (previous_peak > current_peak + 4.0)
        )
    )
    if dark_release_mask.any():
        alpha_zone = np.where(dark_release_mask, 1.0, alpha_zone)

    low_light_neutral_release_mask = (
        (current_peak < _LOW_LIGHT_NEUTRAL_ISOLATION_PEAK)
        & (chroma_spread < 8.0)
        & (previous_chroma >= 8.0)
        & (previous_peak > current_peak + 4.0)
    )
    if low_light_neutral_release_mask.any():
        alpha_zone = np.where(low_light_neutral_release_mask, 1.0, alpha_zone)

    tiny_mask = zone_delta < deadband
    dark_hold_mask = (
        (current_peak < _LOW_LIGHT_HOLD_PEAK)
        & (previous_peak < _LOW_LIGHT_HOLD_PEAK)
        & tiny_mask
        & achromatic
    )
    if dark_hold_mask.any():
        alpha_zone = np.where(dark_hold_mask, 0.0, alpha_zone)
    low_light_damp = (
        (current_peak < _LOW_LIGHT_HOLD_PEAK)
        & achromatic
        & (zone_delta < deadband * 2.0)
        & ~dark_hold_mask
    )
    if low_light_damp.any():
        alpha_zone = np.where(low_light_damp, np.minimum(alpha_zone, tiny_blend), alpha_zone)
    if tiny_mask.any():
        skip_tiny = (current_peak < 20.0) & (
            (previous_peak >= 20.0) | (chroma_spread >= 4.0) | (previous_chroma >= 6.0)
        )
        apply_tiny = tiny_mask & ~skip_tiny & ~dark_hold_mask & ~low_light_damp
        if apply_tiny.any():
            alpha_zone = np.where(apply_tiny, np.minimum(alpha_zone, tiny_blend), alpha_zone)

    bright_mask = (current_peak > 20.0) & (previous_peak > 20.0) & tiny_mask
    if bright_mask.any():
        cur_u8 = np.clip(np.rint(current), 0.0, 255.0).astype(np.uint8, copy=False)
        prev_u8 = np.clip(np.rint(previous), 0.0, 255.0).astype(np.uint8, copy=False)
        _l_c, _c_c, h_c = rgb_u8_to_oklch(cur_u8)
        _l_p, _c_p, h_p = rgb_u8_to_oklch(prev_u8)
        hue_delta = np.abs(np.arctan2(np.sin(h_c - h_p), np.cos(h_c - h_p)))
        hue_osc_mask = bright_mask & (hue_delta > 0.35)
        if hue_osc_mask.any():
            alpha_zone = np.where(hue_osc_mask, np.minimum(alpha_zone, tiny_blend), alpha_zone)

    blended = np.empty_like(current)
    static_mask = zone_delta < (deadband * 1.5)
    if static_mask.any():
        oklab = _oklab_blend_rows(current, previous, alpha_zone)
        linear = previous + (alpha_zone[:, None] * (current - previous))
        blended = np.where(static_mask[:, None], oklab, linear)
    else:
        blended = previous + (alpha_zone[:, None] * (current - previous))
    diagnostics = AdaptiveSmoothingDiagnostics(
        scene_activity=scene_activity,
        median_zone_delta=median_delta,
        max_zone_delta=max_delta,
        min_effective_alpha=float(np.min(alpha_zone)),
        max_effective_alpha=float(np.max(alpha_zone)),
        deadband_active=bool(tiny_mask.any()),
    )
    return blended, diagnostics
