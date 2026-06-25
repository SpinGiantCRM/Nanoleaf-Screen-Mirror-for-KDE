from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass
class BlendHysteresisState:
    scene_activity: str = "static"
    prev_tiny: tuple[bool, ...] = field(default_factory=tuple)
    prev_dark_hold: tuple[bool, ...] = field(default_factory=tuple)
    prev_low_light_damp: tuple[bool, ...] = field(default_factory=tuple)
    prev_dark_release: tuple[bool, ...] = field(default_factory=tuple)
    prev_low_light_neutral_release: tuple[bool, ...] = field(default_factory=tuple)
    prev_black_cut: tuple[bool, ...] = field(default_factory=tuple)
    prev_large_jump: tuple[bool, ...] = field(default_factory=tuple)
    prev_skip_tiny: tuple[bool, ...] = field(default_factory=tuple)
    prev_bright: tuple[bool, ...] = field(default_factory=tuple)
    prev_hue_osc: tuple[bool, ...] = field(default_factory=tuple)
    prev_static: tuple[bool, ...] = field(default_factory=tuple)
    prev_chromatic_static: tuple[bool, ...] = field(default_factory=tuple)
    neighbor_prev_dark: tuple[bool, ...] = field(default_factory=tuple)
    neighbor_prev_low_light_neutral: tuple[bool, ...] = field(default_factory=tuple)
    neighbor_prev_bright_block: tuple[bool, ...] = field(default_factory=tuple)


_DARK_ISOLATION_PEAK_ENTER = 18.0
_DARK_ISOLATION_PEAK_EXIT = 14.0
_BRIGHT_NEIGHBOR_DELTA_ENTER = 24.0
_BRIGHT_NEIGHBOR_DELTA_EXIT = 18.0
_LOW_LIGHT_NEUTRAL_ISOLATION_PEAK_ENTER = 40.0
_LOW_LIGHT_NEUTRAL_ISOLATION_PEAK_EXIT = 32.0
_LOW_LIGHT_NEUTRAL_CHROMA_ENTER = 6.0
_LOW_LIGHT_NEUTRAL_CHROMA_EXIT = 8.0
_LOW_LIGHT_HOLD_PEAK_ENTER = 24.0
_LOW_LIGHT_HOLD_PEAK_EXIT = 20.0
_HUE_STABLE_MIN_CHROMA_ENTER = 10.0
_HUE_STABLE_MIN_CHROMA_EXIT = 8.0
_SCENE_LOW_ENTER = 9.0
_SCENE_LOW_EXIT = 6.0
_SCENE_MEDIUM_ENTER = 24.0
_SCENE_MEDIUM_EXIT = 18.0
_BLACK_CUT_CURRENT_ENTER = 8.0
_BLACK_CUT_CURRENT_EXIT = 12.0
_BLACK_CUT_PREVIOUS_ENTER = 64.0
_BLACK_CUT_PREVIOUS_EXIT = 48.0
_DARK_RELEASE_CURRENT_ENTER = 20.0
_DARK_RELEASE_CURRENT_EXIT = 24.0
_DARK_RELEASE_PREVIOUS_DELTA_ENTER = 8.0
_DARK_RELEASE_PREVIOUS_DELTA_EXIT = 5.0
_DARK_RELEASE_PREVIOUS_PEAK_ENTER = 14.0
_DARK_RELEASE_PREVIOUS_PEAK_EXIT = 12.0
_DARK_RELEASE_PREVIOUS_CHROMA_ENTER = 4.0
_DARK_RELEASE_PREVIOUS_CHROMA_EXIT = 6.0
_DARK_RELEASE_PREVIOUS_DELTA_SOFT_ENTER = 4.0
_DARK_RELEASE_PREVIOUS_DELTA_SOFT_EXIT = 2.0
_LOW_LIGHT_NEUTRAL_RELEASE_CHROMA_ENTER = 8.0
_LOW_LIGHT_NEUTRAL_RELEASE_CHROMA_EXIT = 10.0
_LOW_LIGHT_NEUTRAL_RELEASE_PREVIOUS_CHROMA_ENTER = 8.0
_LOW_LIGHT_NEUTRAL_RELEASE_PREVIOUS_CHROMA_EXIT = 6.0
_LOW_LIGHT_NEUTRAL_RELEASE_PREVIOUS_DELTA_ENTER = 4.0
_LOW_LIGHT_NEUTRAL_RELEASE_PREVIOUS_DELTA_EXIT = 2.0
_SKIP_TINY_CURRENT_ENTER = 20.0
_SKIP_TINY_CURRENT_EXIT = 24.0
_SKIP_TINY_PREVIOUS_ENTER = 20.0
_SKIP_TINY_PREVIOUS_CHROMA_ENTER = 4.0
_SKIP_TINY_PREVIOUS_CHROMA_EXIT = 6.0
_SKIP_TINY_PREVIOUS_CHROMA_SOFT_ENTER = 6.0
_SKIP_TINY_PREVIOUS_CHROMA_SOFT_EXIT = 4.0
_BRIGHT_MASK_PEAK_ENTER = 20.0
_BRIGHT_MASK_PEAK_EXIT = 16.0
_HUE_OSC_ENTER = 0.35
_HUE_OSC_EXIT = 0.30
_ACHROMATIC_ENTER = 4.0
_ACHROMATIC_EXIT = 6.0
_STATIC_MASK_MULTIPLIER_ENTER = 1.5
_STATIC_MASK_MULTIPLIER_EXIT = 1.2
_LOW_LIGHT_DAMP_MULTIPLIER_ENTER = 2.0
_LOW_LIGHT_DAMP_MULTIPLIER_EXIT = 1.75
_SCENE_STATIC_MEDIAN_ENTER_MULT = 1.15
_SCENE_STATIC_MEDIAN_EXIT_MULT = 0.85
_SCENE_STATIC_MEAN_ENTER_MULT = 1.4
_SCENE_STATIC_MEAN_EXIT_MULT = 1.0


def _prev_mask(prev: tuple[bool, ...], size: int) -> np.ndarray | None:
    if not prev or len(prev) != size:
        return None
    return np.asarray(prev, dtype=bool)


def _hyst_lt(
    values: np.ndarray,
    *,
    enter: float,
    exit: float,
    prev: tuple[bool, ...],
) -> np.ndarray:
    previous = _prev_mask(prev, int(values.shape[0]))
    if previous is None:
        return values < enter
    return np.where(previous, values < exit, values < enter)


def _hyst_lte(
    values: np.ndarray,
    *,
    enter: float,
    exit: float,
    prev: tuple[bool, ...],
) -> np.ndarray:
    previous = _prev_mask(prev, int(values.shape[0]))
    if previous is None:
        return values <= enter
    return np.where(previous, values <= exit, values <= enter)


def _hyst_gt(
    values: np.ndarray,
    *,
    enter: float,
    exit: float,
    prev: tuple[bool, ...],
) -> np.ndarray:
    previous = _prev_mask(prev, int(values.shape[0]))
    if previous is None:
        return values > enter
    return np.where(previous, values > exit, values > enter)


def _hyst_gte(
    values: np.ndarray,
    *,
    enter: float,
    exit: float,
    prev: tuple[bool, ...],
) -> np.ndarray:
    previous = _prev_mask(prev, int(values.shape[0]))
    if previous is None:
        return values >= enter
    return np.where(previous, values >= exit, values >= enter)


def _scene_activity_hysteresis(
    median_delta: float,
    mean_delta: float,
    deadband: float,
    prev_scene: str,
) -> str:
    static_med_enter = deadband * _SCENE_STATIC_MEDIAN_ENTER_MULT
    static_mean_enter = deadband * _SCENE_STATIC_MEAN_ENTER_MULT
    static_med_exit = deadband * _SCENE_STATIC_MEDIAN_EXIT_MULT
    static_mean_exit = deadband * _SCENE_STATIC_MEAN_EXIT_MULT

    if prev_scene == "high":
        if median_delta >= _SCENE_MEDIUM_EXIT:
            return "high"
        if median_delta >= _SCENE_LOW_EXIT:
            return "medium"
        if median_delta >= static_med_exit or mean_delta >= static_mean_exit:
            return "low"
        return "static"
    if prev_scene == "medium":
        if median_delta >= _SCENE_MEDIUM_ENTER:
            return "high"
        if median_delta < _SCENE_MEDIUM_EXIT:
            if median_delta < _SCENE_LOW_EXIT and mean_delta < static_mean_exit:
                return "static"
            return "low"
        return "medium"
    if prev_scene == "low":
        if median_delta >= _SCENE_MEDIUM_ENTER:
            return "high"
        if median_delta >= _SCENE_LOW_ENTER:
            return "low"
        if median_delta < static_med_exit and mean_delta < static_mean_exit:
            return "static"
        return "low"
    if median_delta >= _SCENE_MEDIUM_ENTER:
        return "high"
    if median_delta >= _SCENE_LOW_ENTER:
        return "low"
    if median_delta < static_med_enter and mean_delta < static_mean_enter:
        return "static"
    return "low"


def apply_neighbor_blend(
    mapped: np.ndarray,
    *,
    spread_mode: str,
    hysteresis: BlendHysteresisState | None = None,
) -> np.ndarray | tuple[np.ndarray, BlendHysteresisState]:
    mode = str(spread_mode or "balanced").strip().lower()
    weight = {"off": 0.0, "precise": 0.04, "balanced": 0.12, "soft": 0.24}.get(mode, 0.12)
    n = int(mapped.shape[0])
    hyst = hysteresis or BlendHysteresisState()
    if n < 8 or weight <= 0.0:
        if hysteresis is not None:
            return mapped, hyst
        return mapped

    mapped_f = np.asarray(mapped, dtype=np.float32)
    peaks = np.max(mapped_f, axis=1)
    chroma = peaks - np.min(mapped_f, axis=1)
    low_light_neutral_mask = _hyst_lt(
        peaks,
        enter=_LOW_LIGHT_NEUTRAL_ISOLATION_PEAK_ENTER,
        exit=_LOW_LIGHT_NEUTRAL_ISOLATION_PEAK_EXIT,
        prev=hyst.neighbor_prev_low_light_neutral,
    ) & _hyst_lt(
        chroma,
        enter=_LOW_LIGHT_NEUTRAL_CHROMA_ENTER,
        exit=_LOW_LIGHT_NEUTRAL_CHROMA_EXIT,
        prev=(),
    )
    dark_mask = (
        _hyst_lt(
            peaks,
            enter=_DARK_ISOLATION_PEAK_ENTER,
            exit=_DARK_ISOLATION_PEAK_EXIT,
            prev=hyst.neighbor_prev_dark,
        )
        | low_light_neutral_mask
    )
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
    prev_delta = prev_peaks - peaks
    next_delta = next_peaks - peaks
    prev_block = _hyst_gt(
        prev_delta,
        enter=_BRIGHT_NEIGHBOR_DELTA_ENTER,
        exit=_BRIGHT_NEIGHBOR_DELTA_EXIT,
        prev=hyst.neighbor_prev_bright_block,
    )
    next_block = _hyst_gt(
        next_delta,
        enter=_BRIGHT_NEIGHBOR_DELTA_ENTER,
        exit=_BRIGHT_NEIGHBOR_DELTA_EXIT,
        prev=(),
    )
    prev_w = np.where(prev_block, 0.0, prev_w)
    next_w = np.where(next_block, 0.0, next_w)

    total_w = prev_w + next_w
    blended = (
        (1.0 - total_w)[:, None] * mapped_f
        + prev_w[:, None] * prev_neighbor
        + next_w[:, None] * next_neighbor
    )
    active = ~dark_mask
    updated = BlendHysteresisState(
        scene_activity=hyst.scene_activity,
        prev_tiny=hyst.prev_tiny,
        prev_dark_hold=hyst.prev_dark_hold,
        prev_low_light_damp=hyst.prev_low_light_damp,
        prev_dark_release=hyst.prev_dark_release,
        prev_low_light_neutral_release=hyst.prev_low_light_neutral_release,
        prev_black_cut=hyst.prev_black_cut,
        prev_large_jump=hyst.prev_large_jump,
        prev_skip_tiny=hyst.prev_skip_tiny,
        prev_bright=hyst.prev_bright,
        prev_hue_osc=hyst.prev_hue_osc,
        prev_static=hyst.prev_static,
        prev_chromatic_static=hyst.prev_chromatic_static,
        neighbor_prev_dark=tuple(bool(v) for v in dark_mask.tolist()),
        neighbor_prev_low_light_neutral=tuple(bool(v) for v in low_light_neutral_mask.tolist()),
        neighbor_prev_bright_block=tuple(bool(v) for v in (prev_block | next_block).tolist()),
    )
    result = np.where(active[:, None], blended, out)
    if hysteresis is not None:
        return result, updated
    return result


def _oklab_blend_rows(
    current: np.ndarray,
    previous: np.ndarray,
    alpha: np.ndarray,
) -> np.ndarray:
    from nanoleaf_sync.runtime.color_processing import encoded_float_to_oklch

    l_c, c_c, h_c = encoded_float_to_oklch(current)
    l_p, c_p, h_p = encoded_float_to_oklch(previous)
    a = np.clip(alpha.astype(np.float32), 0.0, 1.0)
    l_out = (a * l_c) + ((1.0 - a) * l_p)
    c_out = (a * c_c) + ((1.0 - a) * c_p)
    h_delta = np.arctan2(np.sin(h_c - h_p), np.cos(h_c - h_p))
    h_out = h_p + (a * h_delta)
    return oklch_to_rgb_u8(l_out, c_out, h_out).astype(np.float32, copy=False)


def adaptive_delta_blend(
    *,
    current: np.ndarray,
    previous: np.ndarray,
    smoothing: float,
    smoothing_speed: float = 0.75,
    motion_preset: str = "responsive",
    hysteresis: BlendHysteresisState | None = None,
) -> tuple[np.ndarray, AdaptiveSmoothingDiagnostics, BlendHysteresisState]:
    return adaptive_one_euro_blend(
        current=current,
        previous=previous,
        smoothing=smoothing,
        smoothing_speed=smoothing_speed,
        motion_preset=motion_preset,
        hysteresis=hysteresis,
    )


def adaptive_one_euro_blend(
    *,
    current: np.ndarray,
    previous: np.ndarray,
    smoothing: float,
    smoothing_speed: float = 0.75,
    motion_preset: str = "responsive",
    hysteresis: BlendHysteresisState | None = None,
) -> tuple[np.ndarray, AdaptiveSmoothingDiagnostics, BlendHysteresisState]:
    preset = str(motion_preset or "responsive").strip().lower()
    min_alpha = max(0.0, min(1.0, float(smoothing)))
    speed_gain = np.clip(float(smoothing_speed) / 4.0, 0.0, 1.0) ** 2
    hyst = hysteresis or BlendHysteresisState()

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
        return current, diagnostics, hyst

    deadband = 2.0
    tiny_blend = 0.08
    zone_gamma = 1.10
    scene_boost = {
        "static": 0.0,
        "low": 0.22,
        "medium": 0.44,
        "high": 0.70,
    }
    large_jump_enter = 42.0
    large_jump_exit = 36.0
    jump_alpha_min = 0.72
    if preset == "calm":
        deadband = 3.0
        tiny_blend = 0.03
        zone_gamma = 1.35
        scene_boost = {"static": 0.0, "low": 0.16, "medium": 0.34, "high": 0.56}
        large_jump_enter = 50.0
        large_jump_exit = 42.0
        jump_alpha_min = 0.58
    elif preset == "dynamic":
        deadband = 1.2
        tiny_blend = 0.14
        zone_gamma = 0.90
        scene_boost = {"static": 0.04, "low": 0.30, "medium": 0.55, "high": 0.84}
        large_jump_enter = 34.0
        large_jump_exit = 28.0
        jump_alpha_min = 0.84

    median_delta = float(np.median(zone_delta))
    mean_delta = float(np.mean(zone_delta))
    max_delta = float(np.max(zone_delta))
    scene_activity = _scene_activity_hysteresis(
        median_delta,
        mean_delta,
        deadband,
        hyst.scene_activity,
    )

    zone_motion = np.clip((zone_delta - deadband) / max(1e-6, 64.0 - deadband), 0.0, 1.0)
    zone_motion = np.power(zone_motion, zone_gamma)
    scene_motion = scene_boost[scene_activity]
    adaptive_motion = np.maximum(zone_motion, scene_motion)
    adaptive_motion *= speed_gain
    alpha_zone = min_alpha + (1.0 - min_alpha) * adaptive_motion

    large_change_mask = _hyst_gte(
        zone_delta,
        enter=large_jump_enter,
        exit=large_jump_exit,
        prev=hyst.prev_large_jump,
    )
    if large_change_mask.any():
        fast_floor = jump_alpha_min * (0.65 + 0.35 * speed_gain)
        alpha_zone = np.where(large_change_mask, np.maximum(alpha_zone, fast_floor), alpha_zone)

    current_peak = np.max(current, axis=1)
    previous_peak = np.max(previous, axis=1)
    chroma_spread = current_peak - np.min(current, axis=1)
    previous_chroma = previous_peak - np.min(previous, axis=1)
    achromatic = _hyst_lt(
        chroma_spread,
        enter=_ACHROMATIC_ENTER,
        exit=_ACHROMATIC_EXIT,
        prev=(),
    )
    black_cut_mask = _hyst_lt(
        current_peak,
        enter=_BLACK_CUT_CURRENT_ENTER,
        exit=_BLACK_CUT_CURRENT_EXIT,
        prev=hyst.prev_black_cut,
    ) & _hyst_gt(
        previous_peak,
        enter=_BLACK_CUT_PREVIOUS_ENTER,
        exit=_BLACK_CUT_PREVIOUS_EXIT,
        prev=(),
    )
    if black_cut_mask.any():
        alpha_zone = np.where(black_cut_mask, 1.0, alpha_zone)

    dark_release_mask = _hyst_lt(
        current_peak,
        enter=_DARK_RELEASE_CURRENT_ENTER,
        exit=_DARK_RELEASE_CURRENT_EXIT,
        prev=hyst.prev_dark_release,
    ) & (
        _hyst_gte(
            previous_peak - current_peak,
            enter=_DARK_RELEASE_PREVIOUS_DELTA_ENTER,
            exit=_DARK_RELEASE_PREVIOUS_DELTA_EXIT,
            prev=(),
        )
        | (
            _hyst_gte(
                previous_chroma,
                enter=_DARK_RELEASE_PREVIOUS_CHROMA_ENTER,
                exit=_DARK_RELEASE_PREVIOUS_CHROMA_EXIT,
                prev=(),
            )
            & _hyst_gte(
                previous_peak,
                enter=_DARK_RELEASE_PREVIOUS_PEAK_ENTER,
                exit=_DARK_RELEASE_PREVIOUS_PEAK_EXIT,
                prev=(),
            )
            & _hyst_gt(
                previous_peak - current_peak,
                enter=_DARK_RELEASE_PREVIOUS_DELTA_SOFT_ENTER,
                exit=_DARK_RELEASE_PREVIOUS_DELTA_SOFT_EXIT,
                prev=(),
            )
        )
    )
    if dark_release_mask.any():
        alpha_zone = np.where(dark_release_mask, 1.0, alpha_zone)

    low_light_neutral_release_mask = (
        _hyst_lt(
            current_peak,
            enter=_LOW_LIGHT_NEUTRAL_ISOLATION_PEAK_ENTER,
            exit=_LOW_LIGHT_NEUTRAL_ISOLATION_PEAK_EXIT,
            prev=hyst.prev_low_light_neutral_release,
        )
        & _hyst_lt(
            chroma_spread,
            enter=_LOW_LIGHT_NEUTRAL_RELEASE_CHROMA_ENTER,
            exit=_LOW_LIGHT_NEUTRAL_RELEASE_CHROMA_EXIT,
            prev=(),
        )
        & _hyst_gte(
            previous_chroma,
            enter=_LOW_LIGHT_NEUTRAL_RELEASE_PREVIOUS_CHROMA_ENTER,
            exit=_LOW_LIGHT_NEUTRAL_RELEASE_PREVIOUS_CHROMA_EXIT,
            prev=(),
        )
        & _hyst_gt(
            previous_peak - current_peak,
            enter=_LOW_LIGHT_NEUTRAL_RELEASE_PREVIOUS_DELTA_ENTER,
            exit=_LOW_LIGHT_NEUTRAL_RELEASE_PREVIOUS_DELTA_EXIT,
            prev=(),
        )
    )
    if low_light_neutral_release_mask.any():
        alpha_zone = np.where(low_light_neutral_release_mask, 1.0, alpha_zone)

    tiny_mask = _hyst_lt(
        zone_delta,
        enter=deadband,
        exit=deadband * 0.25,
        prev=hyst.prev_tiny,
    )
    dark_hold_mask = (
        _hyst_lt(
            current_peak,
            enter=_LOW_LIGHT_HOLD_PEAK_ENTER,
            exit=_LOW_LIGHT_HOLD_PEAK_EXIT,
            prev=(),
        )
        & _hyst_lt(
            previous_peak,
            enter=_LOW_LIGHT_HOLD_PEAK_ENTER,
            exit=_LOW_LIGHT_HOLD_PEAK_EXIT,
            prev=(),
        )
        & tiny_mask
        & achromatic
    )
    if dark_hold_mask.any():
        alpha_zone = np.where(dark_hold_mask, 0.0, alpha_zone)
    low_light_damp = (
        _hyst_lt(
            current_peak,
            enter=_LOW_LIGHT_HOLD_PEAK_ENTER,
            exit=_LOW_LIGHT_HOLD_PEAK_EXIT,
            prev=(),
        )
        & achromatic
        & _hyst_lt(
            zone_delta,
            enter=deadband * _LOW_LIGHT_DAMP_MULTIPLIER_ENTER,
            exit=deadband * _LOW_LIGHT_DAMP_MULTIPLIER_EXIT,
            prev=hyst.prev_low_light_damp,
        )
        & ~dark_hold_mask
    )
    if low_light_damp.any():
        alpha_zone = np.where(low_light_damp, np.minimum(alpha_zone, tiny_blend), alpha_zone)
    if tiny_mask.any():
        skip_tiny = _hyst_lt(
            current_peak,
            enter=_SKIP_TINY_CURRENT_ENTER,
            exit=_SKIP_TINY_CURRENT_EXIT,
            prev=hyst.prev_skip_tiny,
        ) & (
            _hyst_gte(
                previous_peak,
                enter=_SKIP_TINY_PREVIOUS_ENTER,
                exit=_BRIGHT_MASK_PEAK_EXIT,
                prev=(),
            )
            | _hyst_gte(
                chroma_spread,
                enter=_SKIP_TINY_PREVIOUS_CHROMA_ENTER,
                exit=_SKIP_TINY_PREVIOUS_CHROMA_EXIT,
                prev=(),
            )
            | _hyst_gte(
                previous_chroma,
                enter=_SKIP_TINY_PREVIOUS_CHROMA_SOFT_ENTER,
                exit=_SKIP_TINY_PREVIOUS_CHROMA_SOFT_EXIT,
                prev=(),
            )
        )
        apply_tiny = tiny_mask & ~skip_tiny & ~dark_hold_mask & ~low_light_damp
        if apply_tiny.any():
            alpha_zone = np.where(apply_tiny, np.minimum(alpha_zone, tiny_blend), alpha_zone)
    else:
        skip_tiny = np.zeros(zone_delta.shape[0], dtype=bool)

    bright_mask = (
        _hyst_gt(
            current_peak,
            enter=_BRIGHT_MASK_PEAK_ENTER,
            exit=_BRIGHT_MASK_PEAK_EXIT,
            prev=hyst.prev_bright,
        )
        & _hyst_gt(
            previous_peak,
            enter=_BRIGHT_MASK_PEAK_ENTER,
            exit=_BRIGHT_MASK_PEAK_EXIT,
            prev=(),
        )
        & tiny_mask
    )
    hue_osc_mask = np.zeros(zone_delta.shape[0], dtype=bool)
    if bright_mask.any():
        cur_u8 = np.clip(np.rint(current), 0.0, 255.0).astype(np.uint8, copy=False)
        prev_u8 = np.clip(np.rint(previous), 0.0, 255.0).astype(np.uint8, copy=False)
        _l_c, _c_c, h_c = rgb_u8_to_oklch(cur_u8)
        _l_p, _c_p, h_p = rgb_u8_to_oklch(prev_u8)
        hue_delta = np.abs(np.arctan2(np.sin(h_c - h_p), np.cos(h_c - h_p)))
        hue_stable = _hyst_gte(
            chroma_spread,
            enter=_HUE_STABLE_MIN_CHROMA_ENTER,
            exit=_HUE_STABLE_MIN_CHROMA_EXIT,
            prev=(),
        ) & _hyst_gte(
            previous_chroma,
            enter=_HUE_STABLE_MIN_CHROMA_ENTER,
            exit=_HUE_STABLE_MIN_CHROMA_EXIT,
            prev=(),
        )
        hue_osc_mask = (
            bright_mask
            & hue_stable
            & _hyst_gt(
                hue_delta,
                enter=_HUE_OSC_ENTER,
                exit=_HUE_OSC_EXIT,
                prev=hyst.prev_hue_osc,
            )
        )
        if hue_osc_mask.any():
            alpha_zone = np.where(hue_osc_mask, np.minimum(alpha_zone, tiny_blend), alpha_zone)

    blended = np.empty_like(current)
    linear = previous + (alpha_zone[:, None] * (current - previous))
    static_mask = _hyst_lt(
        zone_delta,
        enter=deadband * _STATIC_MASK_MULTIPLIER_ENTER,
        exit=deadband * _STATIC_MASK_MULTIPLIER_EXIT,
        prev=hyst.prev_static,
    )
    chromatic_static = np.zeros(zone_delta.shape[0], dtype=bool)
    if static_mask.any():
        chromatic_static = (
            static_mask
            & _hyst_gte(
                chroma_spread,
                enter=_HUE_STABLE_MIN_CHROMA_ENTER,
                exit=_HUE_STABLE_MIN_CHROMA_EXIT,
                prev=hyst.prev_chromatic_static,
            )
            & _hyst_gte(
                previous_chroma,
                enter=_HUE_STABLE_MIN_CHROMA_ENTER,
                exit=_HUE_STABLE_MIN_CHROMA_EXIT,
                prev=(),
            )
        )
        if chromatic_static.any():
            oklab = _oklab_blend_rows(current, previous, alpha_zone)
            blended = np.where(chromatic_static[:, None], oklab, linear)
        else:
            blended = linear
    else:
        blended = linear
    diagnostics = AdaptiveSmoothingDiagnostics(
        scene_activity=scene_activity,
        median_zone_delta=median_delta,
        max_zone_delta=max_delta,
        min_effective_alpha=float(np.min(alpha_zone)),
        max_effective_alpha=float(np.max(alpha_zone)),
        deadband_active=bool(tiny_mask.any()),
    )
    updated = BlendHysteresisState(
        scene_activity=scene_activity,
        prev_tiny=tuple(bool(v) for v in tiny_mask.tolist()),
        prev_dark_hold=tuple(bool(v) for v in dark_hold_mask.tolist()),
        prev_low_light_damp=tuple(bool(v) for v in low_light_damp.tolist()),
        prev_dark_release=tuple(bool(v) for v in dark_release_mask.tolist()),
        prev_low_light_neutral_release=tuple(
            bool(v) for v in low_light_neutral_release_mask.tolist()
        ),
        prev_black_cut=tuple(bool(v) for v in black_cut_mask.tolist()),
        prev_large_jump=tuple(bool(v) for v in large_change_mask.tolist()),
        prev_skip_tiny=tuple(bool(v) for v in skip_tiny.tolist()),
        prev_bright=tuple(bool(v) for v in bright_mask.tolist()),
        prev_hue_osc=tuple(bool(v) for v in hue_osc_mask.tolist()),
        prev_static=tuple(bool(v) for v in static_mask.tolist()),
        prev_chromatic_static=tuple(bool(v) for v in chromatic_static.tolist()),
        neighbor_prev_dark=hyst.neighbor_prev_dark,
        neighbor_prev_low_light_neutral=hyst.neighbor_prev_low_light_neutral,
        neighbor_prev_bright_block=hyst.neighbor_prev_bright_block,
    )
    return blended, diagnostics, updated
