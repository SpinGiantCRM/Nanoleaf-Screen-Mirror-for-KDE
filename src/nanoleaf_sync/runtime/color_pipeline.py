from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import numpy as np

from nanoleaf_sync._coerce import as_float
from nanoleaf_sync.color._types import RGBTuple
from nanoleaf_sync.color.capture_metadata import resolve_compositor_hdr_runtime
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.presets import (
    SAMPLING_MODE_AREA_AVERAGE,
    SAMPLING_MODE_EDGE_DIRECT,
    SAMPLING_MODE_PALETTE_ADAPTIVE,
    SAMPLING_MODE_VIVID_WEIGHTED,
    effective_edge_locality_for_sync,
    effective_light_spread_for_sync,
    effective_motion_and_smoothing,
    effective_sampling_mode,
    effective_zone_sampling_engine_for_sync,
    effective_zone_sampling_stride_for_sync,
    is_accuracy_mode,
    predictive_sync_enabled_for_sync,
)
from nanoleaf_sync.runtime.blending import (
    BlendHysteresisState,
    adaptive_one_euro_blend,
    apply_neighbor_blend,
)
from nanoleaf_sync.runtime.color_processing import (
    LedCalibration,
    apply_color_style_and_led_calibration_with_diagnostics,
    apply_dark_zone_output,
    apply_display_gamut_adaptation,
    apply_output_quantization_hold_with_mask,
    stabilize_dark_zone_samples,
)
from nanoleaf_sync.runtime.compositor import (
    apply_zone_sdr_boost_float,
    effective_sdr_boost,
    zone_sdr_boost_undo_ratio,
)
from nanoleaf_sync.runtime.predictive_sync import PredictiveSyncParams, apply_predictive_sync
from nanoleaf_sync.runtime.srgb import linear01_to_srgb_float, srgb_encoded_float_to_linear01
from nanoleaf_sync.runtime.state import ZoneRect
from nanoleaf_sync.runtime.zones import ZoneSamplingMeta, zone_colors_array_with_meta

if TYPE_CHECKING:
    from nanoleaf_sync.runtime.engine import FrameProcessingTimings


@dataclass(frozen=True)
class ColorPipelineParams:
    brightness: float = 1.0
    smoothing: float = 0.5
    smoothing_speed: float = 0.75
    zone_sampling_stride: int = 1
    zone_sampling_engine: str = "optimized"
    motion_preset: str = "responsive"
    light_spread: str = "balanced"
    color_style: str = "natural"
    edge_locality: str = "balanced"
    sampling_quality: str = "balanced"
    sampling_mode: str = "auto"
    letterbox_detection: bool = True
    compositor_hdr_mode: bool = False
    sdr_boost_nits: float = 80.0
    hdr_max_nits: float = 1000.0
    sdr_boost_compensation_enabled: bool = True
    accuracy_mode: bool = False
    skip_display_gamut_adaptation: bool = False
    color_context: object | None = None
    led_calibration: LedCalibration | None = None
    return_diagnostics: bool = False
    build_zone_diagnostics: bool = False
    sync_mode: str = "standard"
    predictive_sync_strength: float = 0.35
    effective_target_fps: float = 60.0
    config_fps: float = 60.0
    staleness_ms: float = 0.0
    output_healthy: bool = False
    prev_sampled_zone_colors: Sequence[RGBTuple] = ()
    previous_palette_algorithms: Sequence[str] = ()
    zone_palette_temporal_states: Sequence[dict[str, object]] = ()
    palette_frame_index: int = 0
    stabilize_palette_selection: bool = True
    prior_zone_sample_motion: float = 0.0
    prior_area_average_mode: bool = False
    sampling_mode_dwell_remaining: int = 0
    prev_smooth_float_colors: Sequence[tuple[float, float, float]] = ()
    prev_sent_colors: Sequence[RGBTuple] = ()
    dark_zone_stabilize_hold: Sequence[bool] = ()
    blend_hysteresis: BlendHysteresisState | None = None
    output_quantization_prev_hold: Sequence[bool] = ()
    privacy_zones: Sequence[object] = ()
    prev_zone_variance: object | None = None
    virtual_oversample: int = 0
    scene_adaptive_profiles: bool = False
    zone_temporal_accumulation: bool = False
    blue_noise_dither: bool = False
    multi_moment_zone_colors: bool = False
    use_zone_box_filter: bool = False


_SAMPLING_MODE_DWELL_FRAMES = 3


def _resolve_live_sampling_mode(
    *,
    resolved_sampling_mode: str,
    prior_zone_sample_motion: float,
    prior_area_average_mode: bool = False,
    enter_motion: float = 12.0,
    exit_motion: float = 7.0,
    dwell_remaining: int = 0,
) -> tuple[str, bool, int]:
    mode = str(resolved_sampling_mode or "area_average").strip().lower()
    if mode != SAMPLING_MODE_EDGE_DIRECT:
        return mode, False, 0
    motion = float(prior_zone_sample_motion)
    if prior_area_average_mode:
        desired_mode = (
            SAMPLING_MODE_EDGE_DIRECT if motion < exit_motion else SAMPLING_MODE_AREA_AVERAGE
        )
        desired_area = desired_mode == SAMPLING_MODE_AREA_AVERAGE
    else:
        desired_mode = (
            SAMPLING_MODE_AREA_AVERAGE if motion >= enter_motion else SAMPLING_MODE_EDGE_DIRECT
        )
        desired_area = desired_mode == SAMPLING_MODE_AREA_AVERAGE
    if desired_area == prior_area_average_mode:
        return desired_mode, desired_area, 0
    if dwell_remaining > 0:
        held_mode = (
            SAMPLING_MODE_AREA_AVERAGE if prior_area_average_mode else SAMPLING_MODE_EDGE_DIRECT
        )
        return held_mode, prior_area_average_mode, max(0, int(dwell_remaining) - 1)
    return desired_mode, desired_area, _SAMPLING_MODE_DWELL_FRAMES


def _resolve_robust_sampling_mode(
    *,
    resolved_sampling_mode: str,
    prior_zone_sample_motion: float,
    prior_area_average_mode: bool,
    prev_sampled_zone_colors: Sequence[RGBTuple],
    letterbox_active: bool,
    dwell_remaining: int = 0,
) -> tuple[str, bool, int]:
    mode, area_average_active, dwell = _resolve_live_sampling_mode(
        resolved_sampling_mode=resolved_sampling_mode,
        prior_zone_sample_motion=prior_zone_sample_motion,
        prior_area_average_mode=prior_area_average_mode,
        dwell_remaining=dwell_remaining,
    )
    peak_pick_modes = {SAMPLING_MODE_VIVID_WEIGHTED, "peak_luma", SAMPLING_MODE_PALETTE_ADAPTIVE}
    uses_peak_pick = (
        str(resolved_sampling_mode).strip().lower() in peak_pick_modes
        or str(mode).strip().lower() in peak_pick_modes
    )
    if not uses_peak_pick:
        return mode, area_average_active, dwell
    if letterbox_active:
        return SAMPLING_MODE_AREA_AVERAGE, True, dwell
    if prev_sampled_zone_colors:
        prev = np.asarray(prev_sampled_zone_colors, dtype=np.float32)
        if prev.size:
            median_peak = float(np.median(np.max(prev, axis=1)))
            if median_peak < 40.0:
                return SAMPLING_MODE_AREA_AVERAGE, True, dwell
    return mode, area_average_active, dwell


_resolve_dark_aware_sampling_mode = _resolve_robust_sampling_mode


def zone_sample_motion(current: np.ndarray, previous: Sequence[RGBTuple] | None) -> float:
    if previous is None or current.size == 0:
        return 0.0
    n = min(len(previous), int(current.shape[0]))
    if n <= 0:
        return 0.0
    prev = np.asarray(previous[:n], dtype=np.float32)
    cur = current[:n].astype(np.float32, copy=False)
    return float(np.median(np.mean(np.abs(cur - prev), axis=1)))


def process_zone_colors(
    *,
    frame: np.ndarray | None,
    precomputed_zone_colors: np.ndarray | None,
    prev_smoothed_colors: Sequence[RGBTuple],
    zones_px: Sequence[ZoneRect],
    device_zone_indices: Sequence[int],
    params: ColorPipelineParams,
) -> (
    list[RGBTuple]
    | tuple[
        list[RGBTuple],
        np.ndarray,
        np.ndarray,
        np.ndarray,
        FrameProcessingTimings,
        list[tuple[float, float, float]],
        list[RGBTuple],
    ]
):
    if precomputed_zone_colors is None:
        if frame is None or not isinstance(frame, np.ndarray):
            raise RuntimeError(
                f"Capture returned invalid frame type: {type(frame).__name__}; expected np.ndarray"
            )
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise RuntimeError(
                f"Capture returned unexpected frame shape: {getattr(frame, 'shape', None)}"
            )

    from nanoleaf_sync.runtime.engine import FrameProcessingTimings

    timings = FrameProcessingTimings()
    stage_start = time.perf_counter()
    frame_convert_done = stage_start

    prev_smooth = params.prev_smooth_float_colors or prev_smoothed_colors
    prev_sent = params.prev_sent_colors or prev_smoothed_colors

    motion_preset, smoothing, smoothing_speed = effective_motion_and_smoothing(
        motion_preset=params.motion_preset,
        smoothing=params.smoothing,
        smoothing_speed=params.smoothing_speed,
        accuracy_mode=params.accuracy_mode,
        color_style=params.color_style,
        sync_mode=params.sync_mode,
    )
    if params.scene_adaptive_profiles:
        from nanoleaf_sync.runtime.scene_profiles import PROFILES, classify_scene

        chroma_variance = 0.0
        if params.prev_sampled_zone_colors:
            prev_arr = np.asarray(params.prev_sampled_zone_colors, dtype=np.float32)
            if prev_arr.size:
                chroma_variance = float(np.std(prev_arr[:, :3]))
        profile_name = classify_scene(
            motion=float(params.prior_zone_sample_motion),
            letterbox_ratio=0.0,
            chroma_variance=chroma_variance,
        )
        profile = PROFILES.get(profile_name, {})
        motion_preset = str(profile.get("motion_preset", motion_preset))
        smoothing = as_float(profile.get("smoothing"), default=smoothing)
        smoothing_speed = as_float(profile.get("smoothing_speed"), default=smoothing_speed)
        params = replace(
            params,
            color_style=str(profile.get("color_style", params.color_style)),
            light_spread=str(profile.get("light_spread", params.light_spread)),
            effective_target_fps=as_float(profile.get("fps"), default=params.effective_target_fps),
        )
    light_spread = effective_light_spread_for_sync(
        light_spread=params.light_spread,
        accuracy_mode=params.accuracy_mode,
        color_style=params.color_style,
        sync_mode=params.sync_mode,
    )
    edge_locality = effective_edge_locality_for_sync(
        edge_locality=params.edge_locality,
        sync_mode=params.sync_mode,
    )
    zone_sampling_stride = effective_zone_sampling_stride_for_sync(
        sampling_quality=str(getattr(params, "sampling_quality", "balanced")),
        sync_mode=params.sync_mode,
        config_fps=int(max(1.0, float(params.config_fps))),
    )
    accuracy_active = is_accuracy_mode(params.accuracy_mode, params.color_style)
    if accuracy_active:
        zone_sampling_stride = 1
    if zone_sampling_stride <= 0:
        zone_sampling_stride = max(1, int(params.zone_sampling_stride))
    zone_engine = effective_zone_sampling_engine_for_sync(
        zone_sampling_engine=params.zone_sampling_engine,
        accuracy_mode=params.accuracy_mode,
        color_style=params.color_style,
        sync_mode=params.sync_mode,
    )
    resolved_sampling_mode = effective_sampling_mode(
        sampling_mode=params.sampling_mode,
        color_style=params.color_style,
        accuracy_mode=params.accuracy_mode,
    )
    if accuracy_active:
        live_sampling_mode = resolved_sampling_mode
        area_average_active = resolved_sampling_mode == SAMPLING_MODE_AREA_AVERAGE
        sampling_dwell = 0
    else:
        live_sampling_mode, area_average_active, sampling_dwell = _resolve_robust_sampling_mode(
            resolved_sampling_mode=resolved_sampling_mode,
            prior_zone_sample_motion=float(params.prior_zone_sample_motion),
            prior_area_average_mode=bool(params.prior_area_average_mode),
            prev_sampled_zone_colors=params.prev_sampled_zone_colors,
            letterbox_active=False,
            dwell_remaining=int(getattr(params, "sampling_mode_dwell_remaining", 0) or 0),
        )

    letterbox_active = False
    sampling_meta: ZoneSamplingMeta | None = None
    raw_sample_rects = tuple(zones_px) if zones_px else ()
    if precomputed_zone_colors is not None:
        raw_colors = np.asarray(precomputed_zone_colors, dtype=np.uint8)
        if raw_colors.ndim != 2 or raw_colors.shape[1] != 3:
            raise RuntimeError(f"Precomputed zone colors have unexpected shape: {raw_colors.shape}")
        precomputed_sampling_modes = ("precomputed_zone_colors",) * int(raw_colors.shape[0])
    else:
        precomputed_sampling_modes = ()
        from nanoleaf_sync.config.presets import analyzer_mode_for_presets

        analyzer_mode = analyzer_mode_for_presets(
            motion_preset=motion_preset,
            color_style=params.color_style,
        )
        if is_accuracy_mode(params.accuracy_mode, params.color_style):
            analyzer_mode = "balanced"

        sampling_zones = list(zones_px)
        if params.letterbox_detection and frame is not None:
            from nanoleaf_sync.runtime.content_bounds import (
                clip_zones_to_content_bounds,
                detect_content_bounds,
                letterbox_margins_significant,
            )

            bounds = detect_content_bounds(frame)
            letterbox_active = letterbox_margins_significant(frame, bounds)
            if letterbox_active:
                sampling_zones = clip_zones_to_content_bounds(
                    sampling_zones,
                    bounds=bounds,
                    frame_width=int(frame.shape[1]),
                    frame_height=int(frame.shape[0]),
                )
                if not accuracy_active:
                    (
                        live_sampling_mode,
                        area_average_active,
                        sampling_dwell,
                    ) = _resolve_robust_sampling_mode(
                        resolved_sampling_mode=resolved_sampling_mode,
                        prior_zone_sample_motion=float(params.prior_zone_sample_motion),
                        prior_area_average_mode=bool(params.prior_area_average_mode),
                        prev_sampled_zone_colors=params.prev_sampled_zone_colors,
                        letterbox_active=True,
                        dwell_remaining=sampling_dwell,
                    )

        raw_colors, sampling_meta = zone_colors_array_with_meta(
            frame,  # type: ignore[arg-type]
            sampling_zones,
            sample_step=zone_sampling_stride,
            mode=analyzer_mode,
            previous_zone_colors=params.prev_sampled_zone_colors or None,
            edge_locality=edge_locality,
            engine=zone_engine,
            sampling_mode=live_sampling_mode,
            previous_palette_algorithms=params.previous_palette_algorithms or None,
            palette_temporal_states=params.zone_palette_temporal_states or None,
            stabilize_palette=bool(params.stabilize_palette_selection),
            global_scene_cut=float(params.prior_zone_sample_motion) >= 24.0,
            palette_frame_index=int(params.palette_frame_index),
            privacy_zones=params.privacy_zones,  # type: ignore[arg-type]
            prev_zone_variance=(
                np.asarray(params.prev_zone_variance, dtype=np.float32)
                if params.prev_zone_variance is not None
                else None
            ),
            virtual_oversample=int(params.virtual_oversample),
            multi_moment_zone_colors=bool(params.multi_moment_zone_colors),
            use_zone_box_filter=bool(params.use_zone_box_filter),
        )
    if raw_colors.size == 0:
        return []

    if params.zone_temporal_accumulation:
        from nanoleaf_sync.runtime.zone_accumulator import ZoneAccumulator

        if not hasattr(process_zone_colors, "_zone_accumulator"):
            process_zone_colors._zone_accumulator = None  # type: ignore[attr-defined]
        accumulator = process_zone_colors._zone_accumulator  # type: ignore[attr-defined]
        if (
            accumulator is None
            or getattr(accumulator, "_accum", None) is None
            or accumulator._accum.shape[0] != raw_colors.shape[0]
        ):
            accumulator = ZoneAccumulator(raw_colors.shape[0])
            process_zone_colors._zone_accumulator = accumulator  # type: ignore[attr-defined]
        frame_delta = min(1.0, float(params.prior_zone_sample_motion) / 64.0)
        raw_colors = accumulator.update(raw_colors, frame_delta)

    sampling_done = time.perf_counter()

    if isinstance(device_zone_indices, np.ndarray):
        zone_indices = device_zone_indices
    else:
        zone_indices = np.asarray(device_zone_indices, dtype=np.intp)

    if zone_indices.size == 0:
        raise RuntimeError(
            "Device zone mapping is empty; calibration may be incomplete. "
            "Run the calibration wizard to assign zone positions."
        )

    mapped = raw_colors[zone_indices].astype(np.float32, copy=False)
    hold_mask = (
        np.asarray(params.dark_zone_stabilize_hold, dtype=bool)
        if params.dark_zone_stabilize_hold
        else None
    )
    mapped, dark_hold = stabilize_dark_zone_samples(mapped, hold_mask=hold_mask)

    sdr_undo_ratio: np.ndarray | None = None
    boost = effective_sdr_boost(sdr_boost_nits=params.sdr_boost_nits)
    if (
        params.compositor_hdr_mode
        and params.sdr_boost_compensation_enabled
        and abs(boost - 1.0) > 1e-6
    ):
        pre_boost = raw_colors.astype(np.float32, copy=False)
        sdr_undo_ratio = zone_sdr_boost_undo_ratio(pre_boost, sdr_boost_nits=params.sdr_boost_nits)
        mapped = apply_zone_sdr_boost_float(
            mapped,
            sdr_boost_nits=params.sdr_boost_nits,
            hdr_max_nits=params.hdr_max_nits,
        )
    sdr_boost_done = time.perf_counter()

    mapped = apply_display_gamut_adaptation(mapped, color_context=params.color_context)
    capture_colour_stages = bool(params.return_diagnostics or params.build_zone_diagnostics)
    stage_before_style: tuple[tuple[int, int, int], ...] = ()
    stage_after_style: tuple[tuple[int, int, int], ...] = ()
    stage_after_spread: tuple[tuple[int, int, int], ...] = ()
    stage_after_smoothing: tuple[tuple[int, int, int], ...] = ()
    stage_after_led_calibration: tuple[tuple[int, int, int], ...] = ()
    stage_final: tuple[tuple[int, int, int], ...] = ()
    if capture_colour_stages:
        from nanoleaf_sync.runtime.colour_path_diagnostics import snapshot_device_rgb_rows

        def _stage_snapshot(arr: np.ndarray) -> tuple[tuple[int, int, int], ...]:
            return snapshot_device_rgb_rows(arr)

        stage_before_style = _stage_snapshot(mapped)
    calibration = params.led_calibration or LedCalibration()
    mapped, _cap_applied = apply_color_style_and_led_calibration_with_diagnostics(
        mapped,
        color_style=params.color_style,
        calibration=calibration,
    )
    mapped = mapped.astype(np.float32, copy=False)
    if capture_colour_stages:
        stage_after_style = _stage_snapshot(mapped)
    colour_processing_done = time.perf_counter()

    blend_hyst = params.blend_hysteresis or BlendHysteresisState()
    if light_spread != "off":
        mapped, blend_hyst = apply_neighbor_blend(
            mapped,
            spread_mode=light_spread,
            hysteresis=blend_hyst,
        )
        mapped = mapped.astype(np.float32, copy=False)

    b = max(0.0, min(1.0, float(params.brightness)))
    if b != 1.0:
        mapped = linear01_to_srgb_float(srgb_encoded_float_to_linear01(mapped) * b)

    if capture_colour_stages:
        stage_after_spread = _stage_snapshot(mapped)

    pre_led_calibration = (
        np.array(mapped, copy=True)
        if params.return_diagnostics or params.build_zone_diagnostics
        else mapped
    )

    adaptive_diag = None
    if prev_smooth:
        n = min(len(prev_smooth), mapped.shape[0])
        if n:
            prev_arr = np.asarray(prev_smooth[:n], dtype=np.float32)
            mapped[:n], adaptive_diag, blend_hyst = adaptive_one_euro_blend(
                current=mapped[:n],
                previous=prev_arr,
                smoothing=smoothing,
                smoothing_speed=smoothing_speed,
                motion_preset=motion_preset,
                hysteresis=blend_hyst,
            )
    if capture_colour_stages:
        stage_after_smoothing = _stage_snapshot(mapped)
    smoothing_done = time.perf_counter()

    mapped = apply_dark_zone_output(mapped)
    if capture_colour_stages:
        stage_after_led_calibration = _stage_snapshot(mapped)
    led_calibration_done = time.perf_counter()

    sampled_median_peak = float(np.median(np.max(raw_colors.astype(np.float32), axis=1)))
    predictive_active = False
    predictive_lookahead_frames = 0.0
    predictive_scene_cut_suppressed = False
    if predictive_sync_enabled_for_sync(
        sync_mode=params.sync_mode,
        accuracy_mode=params.accuracy_mode,
        color_style=params.color_style,
    ):
        prev_for_pred = (
            np.asarray(prev_smooth[: mapped.shape[0]], dtype=np.float32) if prev_smooth else None
        )
        max_zone_delta = float(adaptive_diag.max_zone_delta) if adaptive_diag is not None else None
        median_zone_delta = (
            float(adaptive_diag.median_zone_delta) if adaptive_diag is not None else None
        )
        pred_result = apply_predictive_sync(
            smoothed=mapped,
            previous=prev_for_pred,
            max_zone_delta=max_zone_delta,
            median_zone_delta=median_zone_delta,
            sampled_median_peak=sampled_median_peak,
            vivid_weighted_active=str(resolved_sampling_mode).strip().lower()
            in {SAMPLING_MODE_VIVID_WEIGHTED, "peak_luma", SAMPLING_MODE_PALETTE_ADAPTIVE},
            sampled_colors=raw_colors.astype(np.float32, copy=False),
            prev_sampled_colors=(
                np.asarray(params.prev_sampled_zone_colors, dtype=np.float32)
                if params.prev_sampled_zone_colors
                else None
            ),
            params=PredictiveSyncParams(
                enabled=True,
                strength=float(params.predictive_sync_strength),
                effective_target_fps=float(params.effective_target_fps),
                config_fps=float(params.config_fps),
                governor_target_fps=float(params.effective_target_fps),
                staleness_ms=float(params.staleness_ms),
                output_healthy=bool(params.output_healthy),
            ),
        )
        mapped = pred_result.colors.astype(np.float32, copy=False)
        predictive_active = bool(pred_result.active)
        predictive_lookahead_frames = float(pred_result.lookahead_frames)
        predictive_scene_cut_suppressed = bool(pred_result.scene_cut_suppressed)

    smooth_float_history: list[tuple[float, float, float]] = (
        [
            (float(row[0]), float(row[1]), float(row[2]))
            for row in mapped.astype(np.float32, copy=False).tolist()
        ]
        if params.return_diagnostics
        else []
    )

    prev_sent_arr: np.ndarray | None = None
    output_quantization_hold_mask: np.ndarray | None = None
    prev_quant_hold = (
        np.asarray(params.output_quantization_prev_hold, dtype=bool)
        if params.output_quantization_prev_hold
        else None
    )
    if prev_sent:
        n = min(len(prev_sent), mapped.shape[0])
        if n:
            prev_sent_arr = np.asarray(prev_sent[:n], dtype=np.float32)
            mapped[:n], output_quantization_hold_mask = apply_output_quantization_hold_with_mask(
                mapped[:n],
                prev_sent_arr,
                effective_target_fps=float(params.effective_target_fps),
                prev_hold=prev_quant_hold[:n] if prev_quant_hold is not None else None,
            )

    np.clip(mapped, 0.0, 255.0, out=mapped)
    if params.blue_noise_dither:
        from nanoleaf_sync.runtime.temporal_dither import apply_temporal_dither

        mapped = apply_temporal_dither(
            mapped,
            frame_index=int(params.palette_frame_index),
        )
    np.rint(mapped, out=mapped)
    out = mapped.astype(np.uint8, copy=False)
    if capture_colour_stages:
        stage_final = _stage_snapshot(out.astype(np.float32, copy=False))
    out_list: list[RGBTuple] = [(int(row[0]), int(row[1]), int(row[2])) for row in out.tolist()]
    sent_history = out_list if params.return_diagnostics else []
    output_prepare_done = time.perf_counter()

    if params.return_diagnostics:
        effective_rects = (
            sampling_meta.effective_sample_rects if sampling_meta is not None else raw_sample_rects
        )
        per_zone_modes = sampling_meta.per_zone_effective_mode if sampling_meta is not None else ()
        if not per_zone_modes and precomputed_sampling_modes:
            per_zone_modes = precomputed_sampling_modes
        per_zone_mixed = sampling_meta.per_zone_mixed_fallback if sampling_meta is not None else ()
        per_zone_palette = (
            sampling_meta.per_zone_palette_diagnostics if sampling_meta is not None else ()
        )
        per_zone_palette_temporal = (
            sampling_meta.per_zone_palette_temporal_states if sampling_meta is not None else ()
        )
        timings = FrameProcessingTimings(
            frame_convert_ms=(frame_convert_done - stage_start) * 1000.0,
            zone_sampling_ms=(sampling_done - frame_convert_done) * 1000.0,
            colour_processing_ms=(colour_processing_done - sdr_boost_done) * 1000.0,
            smoothing_ms=(smoothing_done - colour_processing_done) * 1000.0,
            led_calibration_ms=(led_calibration_done - smoothing_done) * 1000.0,
            output_prepare_ms=(output_prepare_done - led_calibration_done) * 1000.0,
            area_average_active=bool(area_average_active)
            or (sampling_meta is not None and any(sampling_meta.per_zone_mixed_fallback)),
            letterbox_active=bool(letterbox_active),
            raw_sample_rects=raw_sample_rects,
            effective_sample_rects=effective_rects,
            per_zone_sampling_mode=per_zone_modes,
            per_zone_mixed_fallback=per_zone_mixed,
            per_zone_palette_diagnostics=per_zone_palette,
            per_zone_palette_temporal_states=per_zone_palette_temporal,
            per_zone_output_quantization_hold=tuple(
                bool(v) for v in output_quantization_hold_mask.tolist()
            )
            if output_quantization_hold_mask is not None
            else (),
            per_zone_sdr_boost_undo_ratio=tuple(float(v) for v in sdr_undo_ratio.tolist())
            if sdr_undo_ratio is not None
            else (),
            per_zone_variance=(
                tuple(float(v) for v in sampling_meta.per_zone_variance)
                if sampling_meta is not None and sampling_meta.per_zone_variance
                else ()
            ),
            predictive_sync_active=predictive_active,
            predictive_lookahead_frames=predictive_lookahead_frames,
            predictive_scene_cut_suppressed=predictive_scene_cut_suppressed,
            sampling_mode_dwell_remaining=int(sampling_dwell),
            dark_zone_stabilize_hold=tuple(bool(v) for v in dark_hold.tolist()),
            blend_hysteresis=blend_hyst,
            output_quantization_prev_hold=tuple(
                bool(v) for v in output_quantization_hold_mask.tolist()
            )
            if output_quantization_hold_mask is not None
            else (),
            colour_path_before_style=stage_before_style,
            colour_path_after_style=stage_after_style,
            colour_path_after_spread=stage_after_spread,
            colour_path_after_smoothing=stage_after_smoothing,
            colour_path_after_led_calibration=stage_after_led_calibration,
            colour_path_final=stage_final,
        )
        pre_led_arr = (
            pre_led_calibration.astype(np.uint8, copy=False)
            if isinstance(pre_led_calibration, np.ndarray)
            else np.asarray(pre_led_calibration, dtype=np.uint8)
        )
        return (
            out_list,
            raw_colors.astype(np.uint8, copy=False),
            pre_led_arr,
            out,
            timings,
            smooth_float_history,
            sent_history,
        )
    return out_list


def zone_centers_from_zones_px(
    zones_px: Sequence[ZoneRect],
    *,
    frame_width: int,
    frame_height: int,
) -> list[tuple[int, int]]:
    centers: list[tuple[int, int]] = []
    for rect in zones_px:
        x, y, w, h = rect
        cx = int(round(x + (w / 2.0)))
        cy = int(round(y + (h / 2.0)))
        cx = max(0, min(frame_width - 1, cx))
        cy = max(0, min(frame_height - 1, cy))
        centers.append((cx, cy))
    return centers


def build_led_calibration_from_profile(profile: object | None) -> LedCalibration:
    if profile is None:
        return LedCalibration()
    matrix_raw = getattr(profile, "color_matrix", ()) or ()
    matrix = tuple(float(v) for v in matrix_raw)
    return LedCalibration(
        red_gain=float(getattr(profile, "red_gain", 1.0)),
        green_gain=float(getattr(profile, "green_gain", 1.0)),
        blue_gain=float(getattr(profile, "blue_gain", 1.0)),
        led_gamma=float(getattr(profile, "led_gamma", 1.0)),
        white_balance_temperature=float(getattr(profile, "white_balance_temperature", 0.0)),
        chroma_compression=float(getattr(profile, "chroma_compression", 0.0)),
        neutral_luminance_gain=float(getattr(profile, "neutral_luminance_gain", 1.0)),
        black_luminance_cutoff=float(getattr(profile, "black_luminance_cutoff", 0.0032)),
        black_luminance_knee=float(getattr(profile, "black_luminance_knee", 0.0024)),
        dark_sample_stabilize_on=float(getattr(profile, "dark_sample_stabilize_on", 0.008)),
        dark_sample_stabilize_off=float(getattr(profile, "dark_sample_stabilize_off", 0.025)),
        color_matrix=matrix,
    )


def resolve_active_led_profile(
    config: object,
    *,
    capture_display_referred: bool = False,
) -> object | None:
    if capture_display_referred:
        return getattr(config, "led_calibration_profile_sdr", None)

    from nanoleaf_sync.color.capture_metadata import (
        effective_led_profile_key,
        resolve_display_preset,
    )

    preset = resolve_display_preset(
        display_preset=str(getattr(config, "display_preset", "hdr")),
        hdr_transfer=str(getattr(config, "hdr_transfer", AppConfig.hdr_transfer)),
        hdr_primaries=str(getattr(config, "hdr_primaries", AppConfig.hdr_primaries)),
        compositor_hdr_mode=bool(getattr(config, "compositor_hdr_mode", False)),
        sdr_boost_nits=float(getattr(config, "sdr_boost_nits", 80.0)),
    )
    key = effective_led_profile_key(preset.preset)
    if key == "sdr":
        return getattr(config, "led_calibration_profile_sdr", None)
    return getattr(config, "led_calibration_profile_hdr", None)


def build_pipeline_params_from_config(
    config: object,
    *,
    return_diagnostics: bool = False,
    build_zone_diagnostics: bool = False,
    skip_display_gamut_adaptation: bool = False,
    sdr_boost_compensation_enabled: bool = True,
    capture_display_referred: bool = False,
    effective_target_fps: float | None = None,
    config_fps: float | None = None,
    staleness_ms: float | None = None,
    output_healthy: bool = False,
    prev_sampled_zone_colors: Sequence[RGBTuple] = (),
    previous_palette_algorithms: Sequence[str] = (),
    zone_palette_temporal_states: Sequence[dict[str, object]] = (),
    palette_frame_index: int = 0,
    stabilize_palette_selection: bool = True,
    prior_zone_sample_motion: float = 0.0,
    prior_area_average_mode: bool = False,
    sampling_mode_dwell_remaining: int = 0,
    color_context: object | None = None,
    dark_zone_stabilize_hold: Sequence[bool] = (),
    blend_hysteresis: BlendHysteresisState | None = None,
    output_quantization_prev_hold: Sequence[bool] = (),
    prev_zone_variance: object | None = None,
    virtual_oversample: int | None = None,
    scene_adaptive_profiles: bool | None = None,
) -> ColorPipelineParams:
    active_profile = resolve_active_led_profile(
        config,
        capture_display_referred=capture_display_referred,
    )
    sync_mode = str(getattr(config, "sync_mode", "standard") or "standard")
    compositor_hdr_mode, sdr_boost_nits = resolve_compositor_hdr_runtime(
        compositor_hdr_mode=bool(getattr(config, "compositor_hdr_mode", False)),
        sdr_boost_nits=float(getattr(config, "sdr_boost_nits", 80.0)),
    )
    target_fps = float(
        effective_target_fps if effective_target_fps is not None else getattr(config, "fps", 60)
    )
    configured_fps = float(config_fps if config_fps is not None else getattr(config, "fps", 60))
    stale = float(staleness_ms if staleness_ms is not None else 0.0)
    return ColorPipelineParams(
        brightness=float(getattr(config, "brightness", 1.0)),
        smoothing=float(getattr(config, "smoothing", 0.5)),
        smoothing_speed=float(getattr(config, "smoothing_speed", 0.75)),
        zone_sampling_stride=int(getattr(config, "zone_sampling_stride", 1)),
        zone_sampling_engine=str(getattr(config, "zone_sampling_engine", "auto")),
        motion_preset=str(getattr(config, "motion_preset", "responsive")),
        light_spread=str(getattr(config, "light_spread", "balanced")),
        color_style=str(getattr(config, "color_style", "natural")),
        edge_locality=str(getattr(config, "edge_locality", "balanced")),
        sampling_quality=str(getattr(config, "sampling_quality", "balanced")),
        sampling_mode=str(getattr(config, "sampling_mode", "auto")),
        letterbox_detection=bool(getattr(config, "letterbox_detection", True)),
        compositor_hdr_mode=compositor_hdr_mode,
        sdr_boost_nits=sdr_boost_nits,
        hdr_max_nits=float(getattr(config, "hdr_max_nits", 1000.0)),
        sdr_boost_compensation_enabled=bool(sdr_boost_compensation_enabled),
        accuracy_mode=bool(getattr(config, "accuracy_mode", False)),
        skip_display_gamut_adaptation=skip_display_gamut_adaptation,
        led_calibration=build_led_calibration_from_profile(active_profile),
        return_diagnostics=return_diagnostics,
        build_zone_diagnostics=build_zone_diagnostics,
        sync_mode=sync_mode,
        predictive_sync_strength=float(getattr(config, "predictive_sync_strength", 0.35)),
        effective_target_fps=target_fps,
        config_fps=configured_fps,
        staleness_ms=stale,
        output_healthy=bool(output_healthy),
        prev_sampled_zone_colors=prev_sampled_zone_colors,
        previous_palette_algorithms=tuple(str(v) for v in previous_palette_algorithms),
        zone_palette_temporal_states=tuple(dict(row) for row in zone_palette_temporal_states),
        palette_frame_index=int(palette_frame_index),
        stabilize_palette_selection=bool(stabilize_palette_selection),
        prior_zone_sample_motion=float(prior_zone_sample_motion),
        prior_area_average_mode=bool(prior_area_average_mode),
        sampling_mode_dwell_remaining=int(sampling_mode_dwell_remaining),
        color_context=color_context,
        dark_zone_stabilize_hold=tuple(bool(v) for v in dark_zone_stabilize_hold),
        blend_hysteresis=blend_hysteresis,
        output_quantization_prev_hold=tuple(bool(v) for v in output_quantization_prev_hold),
        privacy_zones=tuple(getattr(config, "privacy_zones", ()) or ()),
        prev_zone_variance=prev_zone_variance,
        virtual_oversample=int(
            virtual_oversample
            if virtual_oversample is not None
            else getattr(config, "virtual_zone_oversample", 0) or 0
        ),
        scene_adaptive_profiles=bool(
            scene_adaptive_profiles
            if scene_adaptive_profiles is not None
            else getattr(config, "scene_adaptive_profiles", False)
        ),
        zone_temporal_accumulation=bool(getattr(config, "zone_temporal_accumulation", True)),
        blue_noise_dither=bool(getattr(config, "blue_noise_dither", True)),
        multi_moment_zone_colors=bool(getattr(config, "multi_moment_zone_colors", False)),
        use_zone_box_filter=bool(getattr(config, "zone_box_filter_sampling", True)),
    )
