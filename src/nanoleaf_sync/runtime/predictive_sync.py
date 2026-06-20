from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PredictiveSyncParams:
    enabled: bool
    strength: float
    effective_target_fps: float
    config_fps: float
    staleness_ms: float
    governor_target_fps: float
    output_healthy: bool = False
    scene_cut_max_delta: float = 28.0
    near_black_threshold: float = 20.0
    max_staleness_ms: float = 28.0
    max_extra_step_ratio: float = 0.35
    max_polish_strength: float = 0.35
    base_blend_alpha: float = 0.65
    static_scene_delta_threshold: float = 3.0
    dark_zone_peak_threshold: float = 20.0


@dataclass(frozen=True)
class PredictiveSyncResult:
    colors: np.ndarray
    lookahead_frames: float
    active: bool
    scene_cut_suppressed: bool


def apply_predictive_sync(
    *,
    smoothed: np.ndarray,
    previous: np.ndarray | None,
    params: PredictiveSyncParams,
    max_zone_delta: float | None = None,
    median_zone_delta: float | None = None,
    sampled_median_peak: float | None = None,
    vivid_weighted_active: bool = False,
    sampled_colors: np.ndarray | None = None,
    prev_sampled_colors: np.ndarray | None = None,
) -> PredictiveSyncResult:
    if not params.enabled or smoothed.size == 0:
        return PredictiveSyncResult(
            colors=smoothed,
            lookahead_frames=0.0,
            active=False,
            scene_cut_suppressed=False,
        )
    if previous is None or previous.shape != smoothed.shape:
        return PredictiveSyncResult(
            colors=smoothed,
            lookahead_frames=0.0,
            active=False,
            scene_cut_suppressed=False,
        )

    config_fps = max(1.0, float(params.config_fps))
    frame_ms = 1000.0 / config_fps
    staleness_ms = max(0.0, float(params.staleness_ms))
    strength = max(0.0, min(1.0, float(params.strength)))
    if params.output_healthy or strength <= 0.0:
        return PredictiveSyncResult(
            colors=smoothed,
            lookahead_frames=0.0,
            active=False,
            scene_cut_suppressed=False,
        )

    needs_polish = staleness_ms > frame_ms * 1.25
    if not needs_polish:
        return PredictiveSyncResult(
            colors=smoothed,
            lookahead_frames=0.0,
            active=False,
            scene_cut_suppressed=False,
        )
    if staleness_ms > float(params.max_staleness_ms):
        return PredictiveSyncResult(
            colors=smoothed,
            lookahead_frames=0.0,
            active=False,
            scene_cut_suppressed=False,
        )

    zone_peak = np.max(smoothed, axis=1) if smoothed.ndim == 2 else np.asarray([], dtype=np.float32)
    if zone_peak.size and float(np.median(zone_peak)) < float(params.dark_zone_peak_threshold):
        return PredictiveSyncResult(
            colors=smoothed,
            lookahead_frames=0.0,
            active=False,
            scene_cut_suppressed=False,
        )
    if (
        vivid_weighted_active
        and sampled_median_peak is not None
        and float(sampled_median_peak) < float(params.dark_zone_peak_threshold)
    ):
        return PredictiveSyncResult(
            colors=smoothed,
            lookahead_frames=0.0,
            active=False,
            scene_cut_suppressed=False,
        )
    if (
        vivid_weighted_active
        and sampled_colors is not None
        and prev_sampled_colors is not None
        and sampled_colors.shape == prev_sampled_colors.shape
        and median_zone_delta is not None
        and float(median_zone_delta) < float(params.static_scene_delta_threshold)
    ):
        from nanoleaf_sync.runtime.color_processing import rgb_u8_to_oklch

        cur_u8 = np.clip(np.rint(sampled_colors), 0.0, 255.0).astype(np.uint8, copy=False)
        prev_u8 = np.clip(np.rint(prev_sampled_colors), 0.0, 255.0).astype(np.uint8, copy=False)
        _l_c, _c_c, h_c = rgb_u8_to_oklch(cur_u8)
        _l_p, _c_p, h_p = rgb_u8_to_oklch(prev_u8)
        hue_delta = np.abs(np.arctan2(np.sin(h_c - h_p), np.cos(h_c - h_p)))
        if float(np.median(hue_delta)) > 0.35:
            return PredictiveSyncResult(
                colors=smoothed,
                lookahead_frames=0.0,
                active=False,
                scene_cut_suppressed=False,
            )
    if float(np.max(smoothed)) < float(params.near_black_threshold):
        return PredictiveSyncResult(
            colors=smoothed,
            lookahead_frames=0.0,
            active=False,
            scene_cut_suppressed=False,
        )

    zone_delta = np.mean(np.abs(smoothed - previous), axis=1)
    max_delta = float(np.max(zone_delta)) if zone_delta.size else 0.0
    median_delta = float(np.median(zone_delta)) if zone_delta.size else 0.0
    if max_zone_delta is not None:
        max_delta = max(max_delta, float(max_zone_delta))
    if median_zone_delta is not None:
        median_delta = max(median_delta, float(median_zone_delta))
    if median_delta < float(params.static_scene_delta_threshold):
        return PredictiveSyncResult(
            colors=smoothed,
            lookahead_frames=0.0,
            active=False,
            scene_cut_suppressed=False,
        )
    if max_delta >= float(params.scene_cut_max_delta):
        return PredictiveSyncResult(
            colors=smoothed,
            lookahead_frames=0.0,
            active=False,
            scene_cut_suppressed=True,
        )

    excess_ms = max(0.0, staleness_ms - frame_ms)
    polish_strength = min(
        float(params.max_polish_strength),
        (excess_ms / frame_ms) * strength,
    )
    if polish_strength < 0.02:
        return PredictiveSyncResult(
            colors=smoothed,
            lookahead_frames=0.0,
            active=False,
            scene_cut_suppressed=False,
        )

    blend_t = min(1.0, float(params.base_blend_alpha) + polish_strength)
    polished = previous + (blend_t * (smoothed - previous))
    observed_step = np.abs(smoothed - previous)
    step_cap = np.maximum(observed_step * float(params.max_extra_step_ratio), 1.5)
    delta = polished - smoothed
    delta = np.clip(delta, -step_cap, step_cap)
    polished = smoothed + delta
    np.clip(polished, 0.0, 255.0, out=polished)

    if smoothed.ndim == 2:
        smoothed_peak = np.max(smoothed, axis=1)
        prev_peak = np.max(previous, axis=1)
    else:
        smoothed_peak = np.asarray([], dtype=np.float32)
        prev_peak = np.asarray([], dtype=np.float32)
    if smoothed_peak.size and prev_peak.size == smoothed_peak.size:
        dark_guard = smoothed_peak < float(params.dark_zone_peak_threshold)
        darkening_guard = (prev_peak - smoothed_peak) > 12.0
        leave_unchanged = dark_guard | darkening_guard
        polished = np.where(leave_unchanged[:, None], smoothed, polished)

    polish_frames = excess_ms / frame_ms if frame_ms > 0.0 else 0.0
    return PredictiveSyncResult(
        colors=polished,
        lookahead_frames=float(polish_frames),
        active=True,
        scene_cut_suppressed=False,
    )
