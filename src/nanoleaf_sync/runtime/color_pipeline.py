from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from nanoleaf_sync.color._types import RGBTuple
from nanoleaf_sync.config.presets import (
    effective_light_spread,
    effective_motion_and_smoothing,
    effective_sampling_mode,
    effective_zone_sampling_engine,
    is_accuracy_mode,
)
from nanoleaf_sync.runtime.blending import adaptive_one_euro_blend, apply_neighbor_blend
from nanoleaf_sync.runtime.color_processing import (
    LedCalibration,
    apply_color_style_mapping,
    apply_display_gamut_adaptation,
    apply_led_calibration,
    set_skip_display_gamut_adaptation,
)
from nanoleaf_sync.runtime.compositor import apply_zone_sdr_boost, effective_sdr_boost
from nanoleaf_sync.runtime.state import ZoneRect
from nanoleaf_sync.runtime.zones import zone_colors_array

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
    sampling_mode: str = "auto"
    letterbox_detection: bool = True
    compositor_hdr_mode: bool = False
    sdr_boost_nits: float = 80.0
    hdr_max_nits: float = 1000.0
    accuracy_mode: bool = False
    skip_display_gamut_adaptation: bool = False
    led_calibration: LedCalibration | None = None
    return_diagnostics: bool = False
    build_zone_diagnostics: bool = False


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
    | tuple[list[RGBTuple], np.ndarray, np.ndarray, np.ndarray, FrameProcessingTimings]
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

    motion_preset, smoothing, smoothing_speed = effective_motion_and_smoothing(
        motion_preset=params.motion_preset,
        smoothing=params.smoothing,
        smoothing_speed=params.smoothing_speed,
        accuracy_mode=params.accuracy_mode,
        color_style=params.color_style,
    )
    light_spread = effective_light_spread(
        light_spread=params.light_spread,
        accuracy_mode=params.accuracy_mode,
        color_style=params.color_style,
    )
    zone_engine = effective_zone_sampling_engine(
        zone_sampling_engine=params.zone_sampling_engine,
        accuracy_mode=params.accuracy_mode,
        color_style=params.color_style,
    )
    resolved_sampling_mode = effective_sampling_mode(
        sampling_mode=params.sampling_mode,
        color_style=params.color_style,
        accuracy_mode=params.accuracy_mode,
    )

    if precomputed_zone_colors is not None:
        raw_colors = np.asarray(precomputed_zone_colors, dtype=np.uint8)
        if raw_colors.ndim != 2 or raw_colors.shape[1] != 3:
            raise RuntimeError(f"Precomputed zone colors have unexpected shape: {raw_colors.shape}")
    else:
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
            if letterbox_margins_significant(frame, bounds):
                sampling_zones = clip_zones_to_content_bounds(
                    sampling_zones,
                    bounds=bounds,
                    frame_width=int(frame.shape[1]),
                    frame_height=int(frame.shape[0]),
                )

        raw_colors = zone_colors_array(
            frame,  # type: ignore[arg-type]
            sampling_zones,
            sample_step=params.zone_sampling_stride,
            mode=analyzer_mode,
            previous_zone_colors=prev_smoothed_colors,
            edge_locality=params.edge_locality,
            engine=zone_engine,
            sampling_mode=resolved_sampling_mode,
        )
    if raw_colors.size == 0:
        return []

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

    boost = effective_sdr_boost(sdr_boost_nits=params.sdr_boost_nits)
    if params.compositor_hdr_mode and abs(boost - 1.0) > 1e-6:
        zone_u8 = np.clip(np.rint(mapped), 0.0, 255.0).astype(np.uint8, copy=False)
        zone_u8 = apply_zone_sdr_boost(
            zone_u8,
            sdr_boost_nits=params.sdr_boost_nits,
            hdr_max_nits=params.hdr_max_nits,
        )
        mapped = zone_u8.astype(np.float32, copy=False)
    sdr_boost_done = time.perf_counter()

    set_skip_display_gamut_adaptation(params.skip_display_gamut_adaptation)
    mapped = apply_display_gamut_adaptation(mapped)
    mapped = apply_color_style_mapping(mapped, color_style=params.color_style).astype(
        np.float32, copy=False
    )
    colour_processing_done = time.perf_counter()
    mapped = apply_neighbor_blend(mapped, spread_mode=light_spread).astype(np.float32, copy=False)

    b = max(0.0, min(1.0, float(params.brightness)))
    if b != 1.0:
        mapped *= b

    if prev_smoothed_colors:
        n = min(len(prev_smoothed_colors), mapped.shape[0])
        if n:
            prev_arr = np.asarray(prev_smoothed_colors[:n], dtype=np.float32)
            mapped[:n], _adaptive_diag = adaptive_one_euro_blend(
                current=mapped[:n],
                previous=prev_arr,
                smoothing=smoothing,
                smoothing_speed=smoothing_speed,
                motion_preset=motion_preset,
            )
    smoothing_done = time.perf_counter()

    pre_led_calibration = (
        np.array(mapped, copy=True)
        if params.return_diagnostics or params.build_zone_diagnostics
        else mapped
    )
    calibration = params.led_calibration or LedCalibration()
    mapped = apply_led_calibration(mapped, calibration)
    led_calibration_done = time.perf_counter()

    np.clip(mapped, 0.0, 255.0, out=mapped)
    np.rint(mapped, out=mapped)
    out = mapped.astype(np.uint8, copy=False)
    out_list = [tuple(int(c) for c in row) for row in out.tolist()]
    output_prepare_done = time.perf_counter()

    if params.return_diagnostics:
        timings = FrameProcessingTimings(
            frame_convert_ms=(frame_convert_done - stage_start) * 1000.0,
            zone_sampling_ms=(sampling_done - frame_convert_done) * 1000.0,
            colour_processing_ms=(colour_processing_done - sdr_boost_done) * 1000.0,
            smoothing_ms=(smoothing_done - colour_processing_done) * 1000.0,
            led_calibration_ms=(led_calibration_done - smoothing_done) * 1000.0,
            output_prepare_ms=(output_prepare_done - led_calibration_done) * 1000.0,
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
        color_matrix=matrix,
    )


def resolve_active_led_profile(config: object) -> object | None:
    from nanoleaf_sync.color.capture_metadata import (
        effective_led_profile_key,
        resolve_display_preset,
    )

    preset = resolve_display_preset(
        display_preset=str(getattr(config, "display_preset", "hdr")),
        hdr_transfer=str(getattr(config, "hdr_transfer", "srgb")),
        hdr_primaries=str(getattr(config, "hdr_primaries", "bt709")),
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
) -> ColorPipelineParams:
    active_profile = resolve_active_led_profile(config)
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
        sampling_mode=str(getattr(config, "sampling_mode", "auto")),
        letterbox_detection=bool(getattr(config, "letterbox_detection", True)),
        compositor_hdr_mode=bool(getattr(config, "compositor_hdr_mode", False)),
        sdr_boost_nits=float(getattr(config, "sdr_boost_nits", 80.0)),
        hdr_max_nits=float(getattr(config, "hdr_max_nits", 1000.0)),
        accuracy_mode=bool(getattr(config, "accuracy_mode", False)),
        skip_display_gamut_adaptation=skip_display_gamut_adaptation,
        led_calibration=build_led_calibration_from_profile(active_profile),
        return_diagnostics=return_diagnostics,
        build_zone_diagnostics=build_zone_diagnostics,
    )
