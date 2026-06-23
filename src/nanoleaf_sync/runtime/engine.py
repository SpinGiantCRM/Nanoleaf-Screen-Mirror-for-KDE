"""Frame-processing engine for the mirroring runtime loop.

The functions in this module transform captured RGB frames into device-zone
colors, apply brightness/smoothing, and handle runtime reinitialization hooks.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

import numpy as np

from nanoleaf_sync.capture.latency_probe import (
    STAGE_ACTUAL_WORK,
    STAGE_CAPTURE_CALL,
    STAGE_CAPTURE_SUCCESS_INTERVAL,
    STAGE_CAPTURE_WORKER_LOOP_GAP,
    STAGE_COLOUR_PROCESSING,
    STAGE_END_TO_END_LIVE,
    STAGE_FRAME_AVAILABLE_WAIT,
    STAGE_FRAME_CONVERT,
    STAGE_FRAME_HANDOFF_WAIT,
    STAGE_FRAME_PROCESSING,
    STAGE_HID_ACK_ARRIVAL,
    STAGE_HID_DEVICE_WRITE,
    STAGE_HID_FLUSH_OR_WAIT,
    STAGE_HID_FRAME_BUILD,
    STAGE_HID_WRITE,
    STAGE_IDLE_WAIT,
    STAGE_INFERRED_UNATTRIBUTED_GAP,
    STAGE_LED_CALIBRATION,
    STAGE_LOOP_GAP,
    STAGE_OUTPUT_PREPARE,
    STAGE_PENDING_FRAME_AGE,
    STAGE_RUNTIME_CAPTURE_CALL,
    STAGE_RUNTIME_IDLE_WAIT,
    STAGE_SMOOTHING,
    STAGE_ZONE_SAMPLING,
    FrameTimingSample,
)
from nanoleaf_sync.capture.source_context import build_display_source_context
from nanoleaf_sync.capture.source_identity import SourceIdentityTracker
from nanoleaf_sync.color._types import RGBTuple
from nanoleaf_sync.color.metadata_hysteresis import MetadataHysteresisTracker
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.presets import effective_drm_zone_patch_capture, is_accuracy_mode
from nanoleaf_sync.runtime.blending import (
    AdaptiveSmoothingDiagnostics,
    adaptive_one_euro_blend,
    apply_neighbor_blend,
)
from nanoleaf_sync.runtime.calibration_resolver import (
    CALIBRATION_INCOMPLETE_STATUS,
    CALIBRATION_READY_STATUS,
    evaluate_device_zone_authority,
    resolve_calibration_mapping_from_config,
)
from nanoleaf_sync.runtime.color_context import color_context_from_display_source
from nanoleaf_sync.runtime.color_pipeline import (
    ColorPipelineParams,
    build_pipeline_params_from_config,
    process_zone_colors,
    zone_centers_from_zones_px,
    zone_sample_motion,
)
from nanoleaf_sync.runtime.color_processing import (
    LedCalibration,
    init_gamut_adaptation,
)
from nanoleaf_sync.runtime.fps_governor import (
    FPSGovernor,
    capture_interval_budget_ms,
    governor_min_fps_floor,
)
from nanoleaf_sync.runtime.frame_context import FrameContext, build_frame_context
from nanoleaf_sync.runtime.processing import scale_zones_to_display, zones_from_config
from nanoleaf_sync.runtime.ring_buf import (
    CapturePayload,
    ProcessedPayload,
    SPSCRingBuffer,
)
from nanoleaf_sync.runtime.startup import (
    apply_current_thread_priority,
    reinitialize_backends,
    should_reinitialize,
)
from nanoleaf_sync.runtime.state import (
    DeviceZoneMappingSignature,
    RuntimeState,
    ZoneRect,
)
from nanoleaf_sync.runtime.zone_derivation import derive_source_zone_artifacts

logger = logging.getLogger(__name__)

_WORKER_POLL_INTERVAL_S = 0.002


def _make_fps_governor(config: AppConfig) -> FPSGovernor:
    fps = max(1, int(config.fps))
    return FPSGovernor(initial_fps=fps, min_fps_floor=governor_min_fps_floor(fps))


def _gamut_init_from_config(config: AppConfig) -> None:
    from nanoleaf_sync.color.primaries import invalidate_primaries_cache

    invalidate_primaries_cache()
    gamut = str(getattr(config, "display_gamut", "auto")).strip().lower()
    custom = None
    if gamut == "custom":
        custom = (
            float(getattr(config, "custom_gamut_red_x", 0.64)),
            float(getattr(config, "custom_gamut_red_y", 0.33)),
            float(getattr(config, "custom_gamut_green_x", 0.30)),
            float(getattr(config, "custom_gamut_green_y", 0.60)),
            float(getattr(config, "custom_gamut_blue_x", 0.15)),
            float(getattr(config, "custom_gamut_blue_y", 0.06)),
        )
    init_gamut_adaptation(gamut, custom_chromaticities=custom)


def _no_pending_frame_rate_per_second(events: int, started_at: float) -> str:
    elapsed = max(0.001, time.perf_counter() - started_at)
    return f"{events / elapsed:.2f}"


def _estimate_processing_staleness_ms(
    *,
    captured_at: float,
    now: float,
    hid_output_work_ewma_ms: float | None,
) -> float:
    frame_age_ms = max(0.0, (float(now) - float(captured_at)) * 1000.0)
    expected_output_ms = max(0.0, float(hid_output_work_ewma_ms or 0.0))
    return frame_age_ms + expected_output_ms


def compute_max_send_age_ms(
    *,
    target_fps: float,
    min_max_send_age_ms: float = 60.0,
    budget_multiplier: float = 2.0,
) -> float:
    pace_fps = max(1.0, float(target_fps))
    frame_budget_ms = 1000.0 / pace_fps
    return max(float(min_max_send_age_ms), frame_budget_ms * float(budget_multiplier))


def _frame_context_latency_labels(payload: ProcessedPayload) -> dict[str, str]:
    frame_context_obj = getattr(payload, "frame_context", None)
    if frame_context_obj is None or not isinstance(frame_context_obj, FrameContext):
        return {
            "frame_seq": "unavailable",
            "capture_source_backend": "unavailable",
            "capture_source_id": "unavailable",
            "capture_source_confidence": "unavailable",
            "frame_age_ms": "unavailable",
        }
    frame_age_ms = max(
        0.0,
        (time.perf_counter() - float(frame_context_obj.captured_at_monotonic)) * 1000.0,
    )
    source = frame_context_obj.source
    return {
        "frame_seq": str(frame_context_obj.frame_seq),
        "capture_source_backend": str(source.backend),
        "capture_source_id": str(source.backend_source_id or source.monitor_id or ""),
        "capture_source_confidence": str(source.source_confidence),
        "capture_method": str(frame_context_obj.capture_method),
        "frame_age_ms": f"{frame_age_ms:.1f}",
    }


def evaluate_stale_output_drop(
    *,
    captured_at: float,
    now: float,
    target_fps: float,
    stale_frame_drop_enabled: bool,
    min_max_send_age_ms: float,
    max_send_age_frame_budget_multiplier: float,
) -> tuple[bool, float, float, str]:
    frame_age_ms = max(0.0, (float(now) - float(captured_at)) * 1000.0)
    max_send_age_ms = compute_max_send_age_ms(
        target_fps=target_fps,
        min_max_send_age_ms=min_max_send_age_ms,
        budget_multiplier=max_send_age_frame_budget_multiplier,
    )
    if not stale_frame_drop_enabled:
        return False, frame_age_ms, max_send_age_ms, ""
    if frame_age_ms > max_send_age_ms:
        reason = f"frame_age_ms={frame_age_ms:.1f}>{max_send_age_ms:.1f}"
        return True, frame_age_ms, max_send_age_ms, reason
    return False, frame_age_ms, max_send_age_ms, ""


@dataclass
class PendingFrame:
    frame: np.ndarray | None
    captured_at: float
    precomputed_zone_colors: np.ndarray | None = None


@dataclass(frozen=True)
class FrameProcessingTimings:
    frame_convert_ms: float | None = None
    zone_sampling_ms: float | None = None
    colour_processing_ms: float | None = None
    smoothing_ms: float | None = None
    led_calibration_ms: float | None = None
    output_prepare_ms: float | None = None
    area_average_active: bool = False
    letterbox_active: bool = False
    raw_sample_rects: tuple[tuple[int, int, int, int], ...] = ()
    effective_sample_rects: tuple[tuple[int, int, int, int], ...] = ()
    per_zone_sampling_mode: tuple[str, ...] = ()
    per_zone_mixed_fallback: tuple[bool, ...] = ()
    per_zone_palette_diagnostics: tuple[dict[str, object], ...] = ()
    per_zone_palette_temporal_states: tuple[dict[str, object], ...] = ()
    per_zone_output_quantization_hold: tuple[bool, ...] = ()
    per_zone_sdr_boost_undo_ratio: tuple[float, ...] = ()
    predictive_sync_active: bool = False
    predictive_lookahead_frames: float = 0.0
    predictive_scene_cut_suppressed: bool = False
    sampling_mode_dwell_remaining: int = 0
    dark_zone_stabilize_hold: tuple[bool, ...] = ()
    colour_path_before_style: tuple[tuple[int, int, int], ...] = ()
    colour_path_after_style: tuple[tuple[int, int, int], ...] = ()
    colour_path_after_spread: tuple[tuple[int, int, int], ...] = ()
    colour_path_after_smoothing: tuple[tuple[int, int, int], ...] = ()
    colour_path_after_led_calibration: tuple[tuple[int, int, int], ...] = ()
    colour_path_final: tuple[tuple[int, int, int], ...] = ()


class PendingFrameSlot:
    """Single-slot latest-frame handoff with overwrite metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._pending: PendingFrame | None = None
        self.replaced_frames = 0

    def put_latest(self, frame: np.ndarray, captured_at: float) -> None:
        with self._cond:
            if self._pending is not None:
                self.replaced_frames += 1
            self._pending = PendingFrame(frame=frame, captured_at=captured_at)
            self._cond.notify()

    def pop(self) -> PendingFrame | None:
        with self._lock:
            pending = self._pending
            self._pending = None
            return pending

    def wait(self, timeout: float) -> bool:
        with self._cond:
            return self._cond.wait_for(
                lambda: self._pending is not None,
                timeout=max(0.0, float(timeout)),
            )

    def has_pending(self) -> bool:
        with self._lock:
            return self._pending is not None

    def get_replaced_count(self) -> int:
        with self._lock:
            return int(self.replaced_frames)


def _adaptive_one_euro_blend(
    *,
    current: np.ndarray,
    previous: np.ndarray,
    smoothing: float,
    smoothing_speed: float = 0.75,
    motion_preset: str = "responsive",
) -> tuple[np.ndarray, AdaptiveSmoothingDiagnostics]:
    return adaptive_one_euro_blend(
        current=current,
        previous=previous,
        smoothing=smoothing,
        smoothing_speed=smoothing_speed,
        motion_preset=motion_preset,
    )


def _zone_sampling_diagnostic_fields(
    *,
    zone_index: int,
    default_rect: tuple[int, int, int, int],
    proc_timings: FrameProcessingTimings | None,
) -> dict[str, object]:
    raw_rect = default_rect
    effective_rect = default_rect
    sampling_mode_effective = ""
    mixed_content_fallback = False
    palette_diagnostics: dict[str, object] = {}
    output_quantization_hold_active = False
    sdr_boost_undo_ratio: float | None = None
    if proc_timings is not None:
        raw_rects = getattr(proc_timings, "raw_sample_rects", ()) or ()
        eff_rects = getattr(proc_timings, "effective_sample_rects", ()) or ()
        if zone_index < len(raw_rects):
            raw_rect = raw_rects[zone_index]
        if zone_index < len(eff_rects):
            effective_rect = eff_rects[zone_index]
        modes = getattr(proc_timings, "per_zone_sampling_mode", ()) or ()
        if zone_index < len(modes):
            sampling_mode_effective = str(modes[zone_index])
        mixed_flags = getattr(proc_timings, "per_zone_mixed_fallback", ()) or ()
        if zone_index < len(mixed_flags):
            mixed_content_fallback = bool(mixed_flags[zone_index])
        palette_rows = getattr(proc_timings, "per_zone_palette_diagnostics", ()) or ()
        if zone_index < len(palette_rows):
            palette_diagnostics = dict(palette_rows[zone_index])
        hold_rows = getattr(proc_timings, "per_zone_output_quantization_hold", ()) or ()
        output_quantization_hold_active = (
            bool(hold_rows[zone_index]) if zone_index < len(hold_rows) else False
        )
        undo_ratios = getattr(proc_timings, "per_zone_sdr_boost_undo_ratio", ()) or ()
        if zone_index < len(undo_ratios):
            sdr_boost_undo_ratio = float(undo_ratios[zone_index])
    return {
        "raw_pixel_rect": raw_rect,
        "effective_sample_rect": effective_rect,
        "sampling_mode_effective": sampling_mode_effective,
        "mixed_content_fallback": mixed_content_fallback,
        "sdr_boost_undo_ratio": sdr_boost_undo_ratio,
        "output_quantization_hold_active": output_quantization_hold_active,
        **palette_diagnostics,
    }


def _zones_signature(
    *,
    zones,
    layout_preset: str,
    img_w: int,
    img_h: int,
    layout_inset: float = 0.0,
    layout_scale: float = 1.0,
) -> tuple[int, int, str, float, float, tuple[tuple[float, float, float, float], ...]]:
    return (
        int(img_w),
        int(img_h),
        str(layout_preset),
        float(layout_inset),
        float(layout_scale),
        tuple((float(z.x), float(z.y), float(z.w), float(z.h)) for z in zones),
    )


def _mapping_signature(
    *,
    source_zone_count: int,
    config: AppConfig,
    detected_device_zone_count: int | None,
    source_side_counts: tuple[int, int, int, int] | None = None,
) -> DeviceZoneMappingSignature:
    calibration = config.effective_calibration()
    return (
        int(source_zone_count),
        int(
            getattr(calibration, "device_zone_count", 0)
            or getattr(config, "device_zone_count", 0)
            or 0
        ),
        int(detected_device_zone_count or 0),
        bool(getattr(calibration, "reverse_zones", False)),
        str(getattr(config, "calibration_model", "corner_anchored")),
        int(getattr(calibration, "corner_anchor_top_left", -1)),
        int(getattr(calibration, "corner_anchor_top_right", -1)),
        int(getattr(calibration, "corner_anchor_bottom_right", -1)),
        int(getattr(calibration, "corner_anchor_bottom_left", -1)),
        tuple(int(i) for i in (source_side_counts or ())),
    )


def _ensure_runtime_artifacts(
    *,
    state: RuntimeState,
    config: AppConfig,
    img_w: int,
    img_h: int,
    detected_device_zone_count: int | None = None,
) -> tuple[list[ZoneRect], np.ndarray]:
    zone_artifacts = derive_source_zone_artifacts(
        config=config,
        detected_device_zone_count=detected_device_zone_count,
        frame_width=img_w,
        frame_height=img_h,
    )
    effective_zones = zone_artifacts.zones
    uses_derived_zones = not bool(config.zones)
    zone_sig = _zones_signature(
        zones=effective_zones,
        layout_preset=(
            str(getattr(config, "layout_preset", "edge_strip")) if uses_derived_zones else ""
        ),
        img_w=img_w,
        img_h=img_h,
        layout_inset=float(getattr(config, "layout_inset", 0.0)),
        layout_scale=float(getattr(config, "layout_scale", 1.0)),
    )
    if state.zone_rects_signature != zone_sig or state.cached_zone_rects is None:
        state.cached_zone_rects = zones_from_config(effective_zones, img_w, img_h)
        state.zone_rects_signature = zone_sig
        logger.info(
            "zone-derivation: %s",
            zone_artifacts.diagnostics_text(
                source_mode="user-configured"
                if bool(getattr(config, "zones", []))
                else "auto-derived",
                device_zone_count=int(getattr(config, "device_zone_count", 0) or 0),
            ),
        )

    zones_px = state.cached_zone_rects
    source_zone_count = len(zones_px)

    mapping_sig = _mapping_signature(
        source_zone_count=source_zone_count,
        config=config,
        detected_device_zone_count=detected_device_zone_count,
        source_side_counts=zone_artifacts.side_counts,
    )
    if (
        state.device_zone_mapping_signature != mapping_sig
        or state.cached_device_zone_indices is None
        or state.cached_device_zone_indices_np is None
    ):
        snapshot = resolve_calibration_mapping_from_config(
            config=config,
            source_zone_count=source_zone_count,
            detected_device_zone_count=detected_device_zone_count,
            source_side_counts=zone_artifacts.side_counts,
        )
        state.cached_device_zone_indices = snapshot.device_to_source_indices
        state.cached_device_zone_indices_np = np.asarray(
            state.cached_device_zone_indices, dtype=np.intp
        )
        state.device_zone_mapping_signature = mapping_sig
        if snapshot.calibration_incomplete:
            state.mark_calibration_incomplete(snapshot.status_message)
        else:
            state.calibration_status = CALIBRATION_READY_STATUS
            state.calibration_status_message = ""

    state.latest_zone_side_counts = tuple(
        int(i) for i in (zone_artifacts.side_counts or (0, 0, 0, 0))
    )
    state.latest_edge_sampling_thickness = zone_artifacts.edge_sampling_thickness
    return zones_px, state.cached_device_zone_indices_np


def _apply_neighbor_blend(mapped: np.ndarray, *, spread_mode: str) -> np.ndarray:
    return apply_neighbor_blend(mapped, spread_mode=spread_mode)


def _side_variance_diagnostics(
    *, sampled: np.ndarray, final: np.ndarray, side_counts: tuple[int, int, int, int]
) -> dict[str, dict[str, float | bool]]:
    out: dict[str, dict[str, float | bool]] = {}
    names = ("top", "right", "bottom", "left")
    start = 0
    for name, count in zip(names, side_counts, strict=False):
        end = start + max(0, int(count))
        s = sampled[start:end]
        f = final[start:end]
        sampled_var = float(np.var(s.astype(np.float32))) if s.size else 0.0
        final_var = float(np.var(f.astype(np.float32))) if f.size else 0.0
        flattened = sampled_var > 120.0 and final_var < max(40.0, sampled_var * 0.25)
        out[name] = {
            "sampled_variance": sampled_var,
            "final_variance": final_var,
            "processing_flattened": flattened,
        }
        start = end
    return out


def _resolve_capture_frame_dimensions(
    *,
    frame: np.ndarray | None,
    precomputed: np.ndarray | None,
    capture_backend: object | None,
    fallback_width: int,
    fallback_height: int,
) -> tuple[int, int]:
    if precomputed is not None:
        cap_params = getattr(capture_backend, "params", None)
        width = int(getattr(cap_params, "width", 0) or fallback_width or 480)
        height = int(getattr(cap_params, "height", 0) or fallback_height or 270)
        return width, height
    if frame is not None:
        return int(frame.shape[1]), int(frame.shape[0])
    return int(fallback_width or 480), int(fallback_height or 270)


_SHORT_BLACK_HOLD_MAX_FRAMES = 5
_CAPTURE_CONTINUITY_GAP_S = 0.5


def _clear_pipeline_temporal_state(
    *,
    state: RuntimeState,
    capture_buf: SPSCRingBuffer[CapturePayload] | None = None,
    process_buf: SPSCRingBuffer[ProcessedPayload] | None = None,
    metadata_tracker: MetadataHysteresisTracker | None = None,
) -> None:
    state.clear_smoothing_history()
    state.smoothing_dimension_signature = None
    if capture_buf is not None:
        capture_buf.clear()
    if process_buf is not None:
        process_buf.clear()
    if metadata_tracker is not None:
        metadata_tracker.reset()


def process_frame(
    *,
    frame,
    prev_smoothed_colors: Sequence[RGBTuple],
    zones_px: Sequence[ZoneRect],
    device_zone_indices: Sequence[int],
    brightness: float,
    smoothing: float,
    smoothing_speed: float = 0.75,
    zone_sampling_stride: int = 1,
    zone_sampling_engine: str = "auto",
    led_gamma: float = 1.0,
    motion_preset: str = "responsive",
    light_spread: str = "balanced",
    red_gain: float = 1.0,
    green_gain: float = 1.0,
    blue_gain: float = 1.0,
    white_balance_temperature: float = 0.0,
    chroma_compression: float = 0.0,
    neutral_luminance_gain: float = 1.0,
    black_luminance_cutoff: float = 0.0032,
    black_luminance_knee: float = 0.0024,
    color_style: str = "natural",
    edge_locality: str = "balanced",
    sampling_mode: str = "auto",
    letterbox_detection: bool = True,
    compositor_hdr_mode: bool = False,
    sdr_boost_nits: float = 80.0,
    hdr_max_nits: float = 1000.0,
    sdr_boost_compensation_enabled: bool = True,
    accuracy_mode: bool = False,
    skip_display_gamut_adaptation: bool = False,
    precomputed_zone_colors: np.ndarray | None = None,
    return_diagnostics: bool = False,
    build_zone_diagnostics: bool = False,
    led_calibration: LedCalibration | None = None,
    sync_mode: str = "standard",
    predictive_sync_strength: float = 0.35,
    effective_target_fps: float = 60.0,
    config_fps: float = 60.0,
    staleness_ms: float = 0.0,
    output_healthy: bool = False,
    sampling_quality: str = "balanced",
    prev_sampled_zone_colors: Sequence[RGBTuple] = (),
    previous_palette_algorithms: Sequence[str] = (),
    prior_zone_sample_motion: float = 0.0,
    prior_area_average_mode: bool = False,
    prev_smooth_float_colors: Sequence[RGBTuple] = (),
    prev_sent_colors: Sequence[RGBTuple] = (),
) -> (
    list[RGBTuple]
    | tuple[
        list[RGBTuple],
        np.ndarray,
        np.ndarray,
        np.ndarray,
        FrameProcessingTimings,
        list[RGBTuple],
        list[RGBTuple],
    ]
):
    """Hot-path frame processing via the unified color pipeline contract."""
    calibration = led_calibration or LedCalibration(
        red_gain=red_gain,
        green_gain=green_gain,
        blue_gain=blue_gain,
        led_gamma=led_gamma,
        white_balance_temperature=white_balance_temperature,
        chroma_compression=chroma_compression,
        neutral_luminance_gain=neutral_luminance_gain,
        black_luminance_cutoff=black_luminance_cutoff,
        black_luminance_knee=black_luminance_knee,
    )
    smooth_history = prev_smooth_float_colors if prev_smooth_float_colors else prev_smoothed_colors
    sent_history = prev_sent_colors if prev_sent_colors else prev_smoothed_colors
    params = ColorPipelineParams(
        brightness=brightness,
        smoothing=smoothing,
        smoothing_speed=smoothing_speed,
        zone_sampling_stride=zone_sampling_stride,
        zone_sampling_engine=zone_sampling_engine,
        motion_preset=motion_preset,
        light_spread=light_spread,
        color_style=color_style,
        edge_locality=edge_locality,
        sampling_mode=sampling_mode,
        letterbox_detection=letterbox_detection,
        compositor_hdr_mode=compositor_hdr_mode,
        sdr_boost_nits=sdr_boost_nits,
        hdr_max_nits=hdr_max_nits,
        sdr_boost_compensation_enabled=sdr_boost_compensation_enabled,
        accuracy_mode=accuracy_mode,
        skip_display_gamut_adaptation=skip_display_gamut_adaptation,
        led_calibration=calibration,
        return_diagnostics=return_diagnostics,
        build_zone_diagnostics=build_zone_diagnostics,
        sync_mode=sync_mode,
        predictive_sync_strength=predictive_sync_strength,
        effective_target_fps=effective_target_fps,
        config_fps=config_fps,
        staleness_ms=staleness_ms,
        output_healthy=output_healthy,
        sampling_quality=sampling_quality,
        prev_sampled_zone_colors=prev_sampled_zone_colors,
        previous_palette_algorithms=tuple(str(v) for v in previous_palette_algorithms),
        prior_zone_sample_motion=prior_zone_sample_motion,
        prior_area_average_mode=prior_area_average_mode,
        prev_smooth_float_colors=smooth_history,
        prev_sent_colors=sent_history,
    )
    return process_zone_colors(
        frame=frame if precomputed_zone_colors is None else None,
        precomputed_zone_colors=precomputed_zone_colors,
        prev_smoothed_colors=sent_history,
        zones_px=zones_px,
        device_zone_indices=device_zone_indices,
        params=params,
    )


def _run_loop_pipeline(
    *,
    config: AppConfig,
    state: RuntimeState,
    get_capture,
    get_driver,
    install_drivers,
    close_backends,
    can_mirroring_write: Callable[[], bool] | None = None,
) -> None:
    _gamut_init_from_config(config)
    governor = _make_fps_governor(config)
    state.target_fps = governor.target_fps
    gov_lock = threading.Lock()
    log_interval_s = float(getattr(config, "status_log_interval_s", 5.0))
    error_limit = max(1, int(getattr(config, "max_consecutive_errors", 5)))
    startup_frame_timeout_s = max(0.1, float(getattr(config, "startup_frame_timeout_s", 5.0)))
    startup_started_at = time.perf_counter()

    # Process buffer keeps a small latest-frame window so HID pressure does not
    # force the processing worker to wait behind stale frames.
    capture_buf: SPSCRingBuffer[CapturePayload] = SPSCRingBuffer(capacity=2)
    process_buf: SPSCRingBuffer[ProcessedPayload] = SPSCRingBuffer(capacity=4)

    # ---- shared cross-thread metrics (lock-protected) -------------------
    metrics_lock = threading.Lock()
    latest_capture_backend_name = "unavailable"
    latest_capture_backend_method = ""
    capture_call_ms_latest: float | None = None
    capture_worker_loop_gap_ms_latest: float | None = None
    capture_success_interval_ms_latest: float | None = None
    last_capture_completed_ts: float | None = None
    last_capture_success_ts: float | None = None
    capture_worker_active = False
    capture_worker_error_count = 0
    capture_worker_failures = 0
    process_worker_error_count = 0
    no_pending_frame_events = 0
    no_pending_started_at = time.perf_counter()
    last_sent_zone_count = 0
    ewma_capture_to_send_ms = 0.0
    hid_loop_gap_ewma_ms: float | None = None
    hid_output_work_ewma_ms: float | None = None
    frame_seq: int = 0
    metadata_tracker = MetadataHysteresisTracker()
    source_identity_tracker = SourceIdentityTracker()

    # ---- capture worker -------------------------------------------------
    def _capture_worker() -> None:
        nonlocal capture_worker_active, capture_call_ms_latest
        nonlocal capture_worker_loop_gap_ms_latest, capture_success_interval_ms_latest
        nonlocal last_capture_completed_ts, last_capture_success_ts
        nonlocal latest_capture_backend_name, latest_capture_backend_method
        nonlocal capture_worker_error_count, capture_worker_failures
        nonlocal no_pending_frame_events
        nonlocal frame_seq
        nonlocal process_worker_error_count
        nonlocal hid_output_work_ewma_ms

        apply_current_thread_priority(config=config, state=state, thread_label="capture worker")
        with metrics_lock:
            capture_worker_active = True
        while not state.stop_event.is_set():
            state.reinit_pause.wait(timeout=0.001)
            try:
                if state.is_reinitializing:
                    time.sleep(0.001)
                    continue
                with metrics_lock:
                    gap_ewma = hid_output_work_ewma_ms
                    target_fps_now = min(
                        max(1, int(getattr(config, "fps", 60))),
                        max(1, int(state.target_fps)),
                    )
                capture_interval_ms = capture_interval_budget_ms(
                    target_fps=target_fps_now,
                    hid_output_work_ewma_ms=gap_ewma,
                )
                if capture_interval_ms is not None and last_capture_success_ts is not None:
                    elapsed_ms = (time.perf_counter() - last_capture_success_ts) * 1000.0
                    if elapsed_ms < capture_interval_ms * 0.95:
                        time.sleep(0.001)
                        continue
                cap = get_capture()
                if cap is None:
                    time.sleep(0.001)
                    continue
                backend_name = str(getattr(cap, "name", "unknown"))
                backend_method = str(getattr(cap, "last_capture_path", "") or "")
                capture_start = time.perf_counter()
                zone_rects = list(state.latest_zone_rects_display)
                capture_result = None
                use_drm_rects = effective_drm_zone_patch_capture(
                    drm_zone_patch_capture=bool(getattr(config, "drm_zone_patch_capture", False)),
                    sync_mode=str(getattr(config, "sync_mode", "standard")),
                ) and bool(zone_rects)
                if use_drm_rects:
                    try:
                        capture_result = cap.capture(zone_rects=zone_rects)
                    except TypeError:
                        capture_result = cap.capture()
                else:
                    capture_result = cap.capture()
                capture_end = time.perf_counter()
                call_ms = (capture_end - capture_start) * 1000.0
                with metrics_lock:
                    latest_capture_backend_name = backend_name
                    latest_capture_backend_method = str(
                        getattr(cap, "last_capture_path", "") or backend_method
                    )
                    capture_call_ms_latest = call_ms
                    if last_capture_completed_ts is not None:
                        capture_worker_loop_gap_ms_latest = (
                            capture_end - last_capture_completed_ts
                        ) * 1000.0
                    last_capture_completed_ts = capture_end
                if capture_result is None:
                    continue
                precomputed: np.ndarray | None = None
                frame: np.ndarray | None = None
                if (
                    isinstance(capture_result, np.ndarray)
                    and capture_result.ndim == 2
                    and capture_result.shape[1] == 3
                ):
                    precomputed = capture_result.astype(np.uint8, copy=False)
                else:
                    frame = capture_result
                frame_w, frame_h = _resolve_capture_frame_dimensions(
                    frame=frame,
                    precomputed=precomputed,
                    capture_backend=cap,
                    fallback_width=int(state.last_frame_width or 0),
                    fallback_height=int(state.last_frame_height or 0),
                )
                if last_capture_success_ts is not None:
                    capture_gap_s = capture_end - last_capture_success_ts
                    if capture_gap_s > _CAPTURE_CONTINUITY_GAP_S:
                        _clear_pipeline_temporal_state(
                            state=state,
                            capture_buf=capture_buf,
                            process_buf=process_buf,
                            metadata_tracker=metadata_tracker,
                        )
                with metrics_lock:
                    frame_seq += 1
                    current_frame_seq = frame_seq
                display_source = build_display_source_context(
                    cap,
                    frame_width=frame_w,
                    frame_height=frame_h,
                )
                frame_context = build_frame_context(
                    frame_seq=current_frame_seq,
                    captured_at=capture_end,
                    source=display_source,
                    frame_width=frame_w,
                    frame_height=frame_h,
                    precomputed_zone_colors=precomputed is not None,
                    capture_duration_ms=call_ms,
                )
                if not capture_buf.try_push(
                    CapturePayload(
                        captured_at=capture_end,
                        frame=frame,
                        precomputed_zone_colors=precomputed,
                        frame_context=frame_context,
                    )
                ):
                    logger.debug("capture worker: ring buffer full; dropping frame")
                    with metrics_lock:
                        no_pending_frame_events += 1
                    time.sleep(0.001)
                else:
                    with metrics_lock:
                        if last_capture_success_ts is not None:
                            capture_success_interval_ms_latest = (
                                capture_end - last_capture_success_ts
                            ) * 1000.0
                        last_capture_success_ts = capture_end
                with metrics_lock:
                    capture_worker_failures = 0
            except Exception as exc:
                with metrics_lock:
                    capture_worker_failures += 1
                    capture_worker_error_count += 1
                state.record_error(exc)
                logger.debug("capture worker error: %s", exc)
                time.sleep(0.005)
        with metrics_lock:
            capture_worker_active = False

    # ---- process worker -------------------------------------------------
    process_worker_error: Exception | None = None

    def _process_worker() -> None:
        nonlocal process_worker_error, process_worker_error_count, frame_seq
        apply_current_thread_priority(config=config, state=state, thread_label="process worker")
        while not state.stop_event.is_set():
            state.reinit_pause.wait(timeout=0.001)
            try:
                if state.is_reinitializing:
                    time.sleep(0.001)
                    continue
                payload = capture_buf.pop_latest(timeout=_WORKER_POLL_INTERVAL_S)
                if payload is None:
                    continue

                frame = payload.frame
                precomputed_zone_colors = payload.precomputed_zone_colors
                frame_context_obj = getattr(payload, "frame_context", None)
                frame_context = (
                    frame_context_obj if isinstance(frame_context_obj, FrameContext) else None
                )
                captured_at = payload.captured_at
                state.first_frame_seen = True

                if frame is not None:
                    img_h, img_w, _ = frame.shape
                    mean_brightness = float(np.mean(frame))
                elif precomputed_zone_colors is not None:
                    cap_for_dims = get_capture()
                    cap_params = getattr(cap_for_dims, "params", None)
                    img_w = int(getattr(cap_params, "width", state.last_frame_width or 480))
                    img_h = int(getattr(cap_params, "height", state.last_frame_height or 270))
                    mean_brightness = float(np.mean(precomputed_zone_colors))
                else:
                    continue

                state.latest_frame_mean_brightness = mean_brightness
                if mean_brightness < 2.0:
                    state.consecutive_black_frames += 1
                    state.total_black_frames += 1
                    if state.consecutive_black_frames % 60 == 0:
                        logger.warning(
                            "All-black frames: %d consecutive, "
                            "backend=%s, method=%s, mean_brightness=%.2f",
                            state.consecutive_black_frames,
                            latest_capture_backend_name,
                            latest_capture_backend_method,
                            mean_brightness,
                        )
                else:
                    if state.consecutive_black_frames > _SHORT_BLACK_HOLD_MAX_FRAMES:
                        state.clear_smoothing_history()
                    state.consecutive_black_frames = 0

                dimension_signature = (int(img_w), int(img_h))
                if (
                    state.smoothing_dimension_signature is not None
                    and state.smoothing_dimension_signature != dimension_signature
                ):
                    state.clear_smoothing_history()
                state.smoothing_dimension_signature = dimension_signature

                driver = get_driver()
                if driver is None:
                    continue

                detected_zones = getattr(
                    driver,
                    "reported_zone_count",
                    getattr(driver, "zone_count", None),
                )
                zone_authority = evaluate_device_zone_authority(
                    config=config,
                    detected_device_zone_count=detected_zones,
                )
                state.device_zone_count_source = zone_authority.device_zone_count_source
                state.configured_device_zone_count = zone_authority.configured_device_zone_count
                state.detected_device_zone_count = zone_authority.detected_device_zone_count
                state.effective_device_zone_count = zone_authority.effective_device_zone_count
                state.device_zone_count_mismatch = zone_authority.device_zone_count_mismatch
                state.mapping_repair_required = zone_authority.mapping_repair_required
                state.device_zone_override_active = zone_authority.override_active
                if zone_authority.blocked:
                    state.mark_device_zone_mismatch(
                        zone_authority.message,
                        authority=zone_authority,
                    )
                    state.startup_elapsed_ms = max(
                        0.0,
                        (time.perf_counter() - startup_started_at) * 1000.0,
                    )
                    state.mark_startup(False)
                    state.stop_event.set()
                    logger.warning(
                        "device zone mismatch; screen mirroring will not stream frames: %s",
                        zone_authority.message,
                    )
                    break

                zones_px, device_zone_indices = _ensure_runtime_artifacts(
                    state=state,
                    config=config,
                    img_w=img_w,
                    img_h=img_h,
                    detected_device_zone_count=detected_zones,
                )

                if (
                    state.calibration_status == CALIBRATION_INCOMPLETE_STATUS
                    or len(device_zone_indices) <= 0
                ):
                    mapping_snapshot = resolve_calibration_mapping_from_config(
                        config=config,
                        source_zone_count=len(zones_px),
                        detected_device_zone_count=detected_zones,
                    )
                    message = mapping_snapshot.status_message
                    if len(device_zone_indices) <= 0 and "empty" not in message.lower():
                        message = f"{message} Derived device-zone mapping is empty."
                    state.mark_calibration_incomplete(message)
                    state.startup_elapsed_ms = max(
                        0.0,
                        (time.perf_counter() - startup_started_at) * 1000.0,
                    )
                    state.mark_startup(False)
                    state.stop_event.set()
                    logger.warning(
                        "calibration incomplete; screen mirroring will not stream frames: %s",
                        message,
                    )
                    break

                state.latest_zone_centers = zone_centers_from_zones_px(
                    zones_px,
                    frame_width=img_w,
                    frame_height=img_h,
                )
                display_w = img_w
                display_h = img_h
                cap_for_display = get_capture()
                if cap_for_display is not None:
                    drm_sampler = getattr(cap_for_display, "_drm_zone_sampler", None)
                    if drm_sampler is not None:
                        display_w = int(getattr(drm_sampler, "width", display_w) or display_w)
                        display_h = int(getattr(drm_sampler, "height", display_h) or display_h)
                state.latest_zone_rects_display = scale_zones_to_display(
                    zones_px,
                    capture_width=img_w,
                    capture_height=img_h,
                    display_width=display_w,
                    display_height=display_h,
                )

                build_diagnostics = bool(
                    getattr(config, "verbose", False)
                    or getattr(config, "live_diagnostics_enabled", False)
                )
                with metrics_lock:
                    governor_target_fps = float(governor.target_fps)
                    expected_hid_work_ms = hid_output_work_ewma_ms
                estimated_staleness_ms = _estimate_processing_staleness_ms(
                    captured_at=captured_at,
                    now=time.perf_counter(),
                    hid_output_work_ewma_ms=expected_hid_work_ms,
                )
                cap_backend = get_capture()
                capture_backend_name = str(getattr(cap_backend, "name", "") or "")
                capture_display_referred = capture_backend_name in {
                    "kwin-dbus",
                    "xdg-portal",
                }
                skip_gamut = state.skip_display_gamut_adaptation
                color_context = None
                if frame_context is not None:
                    source = frame_context.source
                    prev_metadata_transitions = int(metadata_tracker.transitions)
                    stabilized_meta = metadata_tracker.update(source.hdr_metadata)
                    if stabilized_meta is not source.hdr_metadata:
                        source = replace(source, hdr_metadata=stabilized_meta)
                        frame_context = replace(frame_context, source=source)
                    color_context = color_context_from_display_source(source)
                    skip_gamut = bool(color_context.skip_display_gamut_adaptation)
                    state.skip_display_gamut_adaptation = skip_gamut
                    capture_display_referred = bool(color_context.display_referred)
                    identity, identity_changed = source_identity_tracker.observe(
                        source,
                        hdr_metadata_confidence=color_context.confidence,
                    )
                    state.capture_source_change_count = int(source_identity_tracker.change_count)
                    state.latest_capture_source_identity = {
                        **identity.as_dict(),
                        "change_count": source_identity_tracker.change_count,
                    }
                    state.metadata_hysteresis_transitions = int(metadata_tracker.transitions)
                    if metadata_tracker.transitions > prev_metadata_transitions:
                        state.clear_smoothing_history()
                    if identity_changed:
                        logger.warning("Capture source identity changed during mirroring session")
                        _clear_pipeline_temporal_state(
                            state=state,
                            capture_buf=capture_buf,
                            process_buf=process_buf,
                        )
                    state.latest_frame_context = frame_context
                    state.latest_color_context = color_context
                    if state.first_frame_seen and not state.first_frame_sent:
                        state.lifecycle_state = "waiting_for_first_frame"
                elif cap_backend is not None:
                    hdr_diag = getattr(cap_backend, "last_hdr_diagnostics", None) or {}
                    if isinstance(hdr_diag, dict):
                        state.skip_display_gamut_adaptation = bool(
                            hdr_diag.get("skip_display_gamut_adaptation", False)
                        )
                        capture_display_referred = capture_display_referred or bool(
                            hdr_diag.get("tone_mapping_applied", False)
                        )
                        skip_gamut = bool(state.skip_display_gamut_adaptation)
                state.sdr_boost_compensation_enabled = (
                    bool(getattr(config, "compositor_hdr_mode", False))
                    and not capture_display_referred
                )
                pipeline_params = build_pipeline_params_from_config(
                    config,
                    return_diagnostics=True,
                    build_zone_diagnostics=build_diagnostics,
                    skip_display_gamut_adaptation=skip_gamut,
                    sdr_boost_compensation_enabled=state.sdr_boost_compensation_enabled,
                    capture_display_referred=capture_display_referred,
                    effective_target_fps=governor_target_fps,
                    config_fps=float(getattr(config, "fps", 60)),
                    staleness_ms=estimated_staleness_ms,
                    output_healthy=bool(state.output_healthy),
                    prev_sampled_zone_colors=state.prev_sampled_zone_colors,
                    previous_palette_algorithms=state.prev_palette_algorithms,
                    zone_palette_temporal_states=state.zone_palette_temporal_states,
                    palette_frame_index=int(state.palette_frame_index),
                    stabilize_palette_selection=not is_accuracy_mode(
                        bool(getattr(config, "accuracy_mode", False)),
                        str(getattr(config, "color_style", "natural")),
                    ),
                    prior_zone_sample_motion=float(state.prior_zone_sample_motion),
                    prior_area_average_mode=bool(state.prior_area_average_mode),
                    sampling_mode_dwell_remaining=int(state.sampling_mode_dwell_remaining),
                    color_context=color_context,
                    dark_zone_stabilize_hold=state.dark_zone_stabilize_hold,
                )
                light_spread = pipeline_params.light_spread
                if state.flattening_mitigation_active:
                    light_spread = "off"
                processed = process_frame(
                    frame=frame,
                    precomputed_zone_colors=precomputed_zone_colors,
                    prev_smoothed_colors=state.prev_sent_colors or state.prev_smoothed_colors,
                    prev_smooth_float_colors=(
                        state.prev_smooth_float_colors or state.prev_smoothed_colors
                    ),
                    prev_sent_colors=state.prev_sent_colors or state.prev_smoothed_colors,
                    zones_px=zones_px,
                    device_zone_indices=device_zone_indices,  # type: ignore[arg-type]
                    compositor_hdr_mode=pipeline_params.compositor_hdr_mode,
                    sdr_boost_nits=pipeline_params.sdr_boost_nits,
                    hdr_max_nits=pipeline_params.hdr_max_nits,
                    sdr_boost_compensation_enabled=(pipeline_params.sdr_boost_compensation_enabled),
                    accuracy_mode=pipeline_params.accuracy_mode,
                    skip_display_gamut_adaptation=pipeline_params.skip_display_gamut_adaptation,
                    brightness=pipeline_params.brightness,
                    smoothing=pipeline_params.smoothing,
                    smoothing_speed=pipeline_params.smoothing_speed,
                    zone_sampling_stride=pipeline_params.zone_sampling_stride,
                    zone_sampling_engine=pipeline_params.zone_sampling_engine,
                    motion_preset=pipeline_params.motion_preset,
                    light_spread=light_spread,
                    color_style=pipeline_params.color_style,
                    edge_locality=pipeline_params.edge_locality,
                    sampling_mode=pipeline_params.sampling_mode,
                    letterbox_detection=pipeline_params.letterbox_detection,
                    led_calibration=pipeline_params.led_calibration,
                    sync_mode=pipeline_params.sync_mode,
                    predictive_sync_strength=pipeline_params.predictive_sync_strength,
                    effective_target_fps=pipeline_params.effective_target_fps,
                    config_fps=pipeline_params.config_fps,
                    staleness_ms=pipeline_params.staleness_ms,
                    output_healthy=pipeline_params.output_healthy,
                    sampling_quality=pipeline_params.sampling_quality,
                    prev_sampled_zone_colors=pipeline_params.prev_sampled_zone_colors,
                    previous_palette_algorithms=pipeline_params.previous_palette_algorithms,
                    prior_zone_sample_motion=pipeline_params.prior_zone_sample_motion,
                    prior_area_average_mode=pipeline_params.prior_area_average_mode,
                    return_diagnostics=True,
                    build_zone_diagnostics=build_diagnostics,
                )
                (
                    smoothed_colors,
                    sampled_zone_colors,
                    pre_led_colors,
                    final_zone_colors,
                    processing_timings,
                    smooth_float_history,
                    sent_history,
                ) = processed

                if (
                    mean_brightness < 2.0
                    and 0 < state.consecutive_black_frames <= _SHORT_BLACK_HOLD_MAX_FRAMES
                    and state.prev_sent_colors
                    and state.first_frame_sent
                ):
                    smoothed_colors = [list(row) for row in state.prev_sent_colors]

                state.predictive_sync_active = bool(
                    getattr(processing_timings, "predictive_sync_active", False)
                )
                state.predictive_lookahead_frames = float(
                    getattr(processing_timings, "predictive_lookahead_frames", 0.0) or 0.0
                )
                state.predictive_scene_cut_suppressed = bool(
                    getattr(processing_timings, "predictive_scene_cut_suppressed", False)
                )
                state.prior_area_average_mode = bool(
                    getattr(processing_timings, "area_average_active", False)
                )
                state.sampling_mode_dwell_remaining = int(
                    getattr(processing_timings, "sampling_mode_dwell_remaining", 0) or 0
                )
                dark_hold = getattr(processing_timings, "dark_zone_stabilize_hold", ())
                if dark_hold:
                    state.dark_zone_stabilize_hold = [bool(v) for v in dark_hold]
                state.prior_zone_sample_motion = zone_sample_motion(
                    sampled_zone_colors,
                    state.prev_sampled_zone_colors,  # type: ignore[arg-type]
                )
                state.prev_sampled_zone_colors = [
                    tuple(int(c) for c in row)
                    for row in sampled_zone_colors.tolist()  # type: ignore[union-attr]
                ]
                palette_modes = getattr(processing_timings, "per_zone_sampling_mode", ()) or ()
                state.prev_palette_algorithms = [str(v) for v in palette_modes]
                temporal_states = (
                    getattr(processing_timings, "per_zone_palette_temporal_states", ()) or ()
                )
                state.zone_palette_temporal_states = [dict(row) for row in temporal_states]
                state.palette_frame_index += 1
                state.first_frame_processed = True
                state.last_frame_width = int(img_w)
                state.last_frame_height = int(img_h)
                if frame is not None:
                    state.latest_frame_rgb = frame
                state.latest_zones_px = list(zones_px)

                side_var = _side_variance_diagnostics(
                    sampled=sampled_zone_colors,  # type: ignore[arg-type]
                    final=final_zone_colors,  # type: ignore[arg-type]
                    side_counts=state.latest_zone_side_counts,
                )
                state.latest_side_variance_diagnostics = side_var
                state.flattening_mitigation_active = any(
                    bool(side.get("processing_flattened", False)) for side in side_var.values()
                )

                zone_diagnostics: list[dict[str, object]] = []
                if build_diagnostics:
                    from nanoleaf_sync.runtime.colour_path_diagnostics import (
                        build_zone_colour_path_row,
                        resolve_mapped_led_index,
                        resolve_zone_side,
                    )

                    for zone_index, rect in enumerate(zones_px):
                        sampled_rgb = tuple(
                            int(c)
                            for c in sampled_zone_colors[zone_index].tolist()  # type: ignore[union-attr]
                        )
                        mapped_led_index = resolve_mapped_led_index(
                            zone_index,
                            device_zone_indices,
                        )
                        if mapped_led_index is None:
                            pre_led_rgb = sampled_rgb
                            final_rgb = sampled_rgb
                        else:
                            pre_led_rgb = tuple(
                                int(c)
                                for c in pre_led_colors[mapped_led_index].tolist()  # type: ignore[union-attr]
                            )
                            final_rgb = tuple(
                                int(c)
                                for c in final_zone_colors[mapped_led_index].tolist()  # type: ignore[union-attr]
                            )
                        side = resolve_zone_side(
                            zone_index,
                            state.latest_zone_side_counts,
                        )
                        zone_diagnostics.append(
                            build_zone_colour_path_row(
                                zone_index=zone_index,
                                rect=rect,
                                side=side,
                                sampled_rgb=sampled_rgb,
                                mapped_led_index=mapped_led_index,
                                pre_led_rgb=pre_led_rgb,
                                final_rgb=final_rgb,
                                proc_timings=processing_timings,
                                sampling_fields=_zone_sampling_diagnostic_fields(
                                    zone_index=zone_index,
                                    default_rect=rect,
                                    proc_timings=processing_timings,
                                ),
                                color_style=str(getattr(config, "color_style", "reference")),
                            )
                        )
                    for row in zone_diagnostics:
                        row["side_variance"] = side_var.get(str(row.get("side")), {})  # type: ignore[attr-defined]
                        row["processing_flattened_side"] = bool(
                            row["side_variance"].get("processing_flattened", False)  # type: ignore[attr-defined]
                        )
                    state.latest_zone_diagnostics = zone_diagnostics

                replaced_queued_processed_frame = process_buf.push_latest(
                    ProcessedPayload(
                        smoothed_colors=smoothed_colors,  # type: ignore[arg-type]
                        smooth_float_history=smooth_float_history,  # type: ignore[arg-type]
                        sent_history=sent_history,  # type: ignore[arg-type]
                        captured_at=captured_at,
                        zones_px=list(zones_px),
                        device_zone_indices=device_zone_indices,
                        sampled_zone_colors=sampled_zone_colors,  # type: ignore[arg-type]
                        pre_led_colors=pre_led_colors,  # type: ignore[arg-type]
                        final_zone_colors=final_zone_colors,  # type: ignore[arg-type]
                        processing_timings=processing_timings,
                        zone_diagnostics=zone_diagnostics,
                        side_var=side_var,
                        frame_context=frame_context,
                        color_context=color_context,
                    )
                )
                if replaced_queued_processed_frame:
                    logger.debug(
                        "process worker: replaced stale processed frame queued for HID writer"
                    )
                    time.sleep(0.001)
                else:
                    time.sleep(0.001)
                process_worker_error = None
                with metrics_lock:
                    process_worker_error_count = 0
            except Exception as exc:
                process_worker_error = exc
                with metrics_lock:
                    process_worker_error_count += 1
                state.record_error(exc)
                logger.debug("process worker error: %s", exc)
                time.sleep(0.001)

    # ---- HID writer -----------------------------------------------------
    def _hid_writer() -> None:
        nonlocal last_sent_zone_count, ewma_capture_to_send_ms, frame_seq, governor
        nonlocal hid_loop_gap_ewma_ms, hid_output_work_ewma_ms
        apply_current_thread_priority(config=config, state=state, thread_label="hid writer")
        sent_in_window = 0
        last_log = time.perf_counter()
        last_send_done_ts: float | None = None
        next_send_deadline_ts: float | None = None
        idle_poll_ms = _WORKER_POLL_INTERVAL_S * 1000.0

        while not state.stop_event.is_set():
            state.reinit_pause.wait(timeout=0.001)
            try:
                if state.is_reinitializing:
                    time.sleep(0.001)
                    continue
                payload = process_buf.pop_latest(timeout=_WORKER_POLL_INTERVAL_S)
                coalesced_sends = int(process_buf.last_pop_coalesced)
                now = time.perf_counter()

                if payload is None:
                    # idle tick: update latency probe with idle stages only
                    with metrics_lock:
                        cap_active = bool(capture_worker_active)
                        no_pending_events = no_pending_frame_events
                    state.latency_probe.add_stage_sample(
                        FrameTimingSample(
                            stage_ms={
                                STAGE_CAPTURE_CALL: capture_call_ms_latest,
                                STAGE_RUNTIME_CAPTURE_CALL: capture_call_ms_latest,
                                STAGE_CAPTURE_WORKER_LOOP_GAP: capture_worker_loop_gap_ms_latest,
                                STAGE_CAPTURE_SUCCESS_INTERVAL: capture_success_interval_ms_latest,
                                STAGE_FRAME_HANDOFF_WAIT: None,
                                STAGE_FRAME_AVAILABLE_WAIT: idle_poll_ms,
                                STAGE_IDLE_WAIT: idle_poll_ms,
                                STAGE_RUNTIME_IDLE_WAIT: idle_poll_ms,
                                STAGE_FRAME_PROCESSING: None,
                                STAGE_ACTUAL_WORK: None,
                                STAGE_LOOP_GAP: None,
                            },
                            target_fps=float(governor.target_fps),
                            fps_cap=float(governor.target_fps),
                            fps_cap_reason="FPS governor dynamic cap",
                            dropped_or_skipped_frames_delta=0,
                            counters_delta={},
                            flags={"capture_worker_active": cap_active},
                            labels={
                                "latest_capture_backend_name": latest_capture_backend_name,
                                "capture_backend_method": latest_capture_backend_method,
                                "no_pending_frame_rate_per_second": (
                                    _no_pending_frame_rate_per_second(
                                        no_pending_events, no_pending_started_at
                                    )
                                ),
                            },
                        )
                    )
                    continue

                driver = get_driver()
                if driver is None:
                    continue
                if can_mirroring_write is not None and not can_mirroring_write():
                    state.output_owner_dropped_frames += 1
                    continue

                pace_fps = min(
                    max(1, int(getattr(config, "fps", 60))),
                    max(1, int(governor.target_fps)),
                )
                if next_send_deadline_ts is not None and now < next_send_deadline_ts:
                    wait_s = next_send_deadline_ts - now
                    if wait_s > 0.0005:
                        time.sleep(min(wait_s, _WORKER_POLL_INTERVAL_S))
                    continue

                if hasattr(driver, "_live_target_fps"):
                    driver._live_target_fps = int(governor.target_fps)

                should_drop_stale, frame_age_ms, max_send_age_ms, stale_reason = (
                    evaluate_stale_output_drop(
                        captured_at=payload.captured_at,
                        now=now,
                        target_fps=float(pace_fps),
                        stale_frame_drop_enabled=bool(
                            getattr(config, "stale_frame_drop_enabled", True)
                        ),
                        min_max_send_age_ms=float(getattr(config, "min_max_send_age_ms", 60.0)),
                        max_send_age_frame_budget_multiplier=float(
                            getattr(config, "max_send_age_frame_budget_multiplier", 2.0)
                        ),
                    )
                )
                if should_drop_stale:
                    state.record_stale_output_drop(
                        frame_age_ms=frame_age_ms,
                        max_send_age_ms=max_send_age_ms,
                        reason=stale_reason,
                    )
                    with metrics_lock:
                        cap_active = bool(capture_worker_active)
                    state.latency_probe.add_stage_sample(
                        FrameTimingSample(
                            stage_ms={
                                STAGE_PENDING_FRAME_AGE: frame_age_ms,
                            },
                            target_fps=float(governor.target_fps),
                            fps_cap=float(governor.target_fps),
                            fps_cap_reason="FPS governor dynamic cap",
                            dropped_or_skipped_frames_delta=1,
                            counters_delta={
                                "stale_output_dropped_frames": 1,
                            },
                            flags={"capture_worker_active": cap_active},
                            labels={
                                "stale_drop_reason": stale_reason,
                                "max_send_age_ms": f"{max_send_age_ms:.1f}",
                            },
                        )
                    )
                    continue

                outgoing_colors = [tuple(int(c) for c in row) for row in payload.smoothed_colors]
                if (
                    state.first_frame_sent
                    and state.prev_sent_colors
                    and outgoing_colors == state.prev_sent_colors
                ):
                    state.duplicate_output_skipped_frames += 1
                    with metrics_lock:
                        cap_active = bool(capture_worker_active)
                    state.latency_probe.add_stage_sample(
                        FrameTimingSample(
                            stage_ms={},
                            target_fps=float(governor.target_fps),
                            fps_cap=float(governor.target_fps),
                            fps_cap_reason="FPS governor dynamic cap",
                            dropped_or_skipped_frames_delta=1,
                            counters_delta={"duplicate_output_skipped_frames": 1},
                            flags={"capture_worker_active": cap_active},
                            labels={"duplicate_output_skip": "unchanged_zone_colors"},
                        )
                    )
                    continue

                # HID write
                hid_write_start = time.perf_counter()
                hid_frame_build_ms: float | None = None
                hid_device_write_ms: float | None = None
                hid_flush_or_wait_ms: float | None = None
                hid_ack_arrival_ms: float | None = None
                hid_flush_or_wait_reason = "Not instrumented by current driver path."
                hid_frame_build_reason = (
                    "Frame-build timing not separated from send_frame() in driver path."
                )
                hid_device_limited_label = "unknown"
                hid_reports_per_frame = "unavailable"
                hid_bytes_per_report = "unavailable"
                hid_total_frame_bytes = "unavailable"
                hid_report_data_sizes = "unavailable"
                hid_per_report_write_ms = "unavailable"
                hid_write_blocking = "unknown"
                hid_write_retry_policy = "unknown"
                hid_write_rate_limit_policy = "unknown"
                hid_write_read_calls = "unavailable"
                hid_live_send_policy = "response_required"
                hid_response_wait_skipped = "no"

                send_with_timing = getattr(driver, "send_frame_with_timing", None)
                if callable(send_with_timing):
                    timing = send_with_timing(payload.smoothed_colors)
                    hid_frame_build_ms = (
                        float(timing.get("frame_build_ms"))  # type: ignore[arg-type]
                        if isinstance(timing, dict) and timing.get("frame_build_ms") is not None
                        else None
                    )
                    hid_device_write_ms = (
                        float(timing.get("device_write_ms"))  # type: ignore[arg-type]
                        if isinstance(timing, dict) and timing.get("device_write_ms") is not None
                        else None
                    )
                    hid_flush_or_wait_ms = (
                        float(timing.get("flush_or_wait_ms"))  # type: ignore[arg-type]
                        if isinstance(timing, dict) and timing.get("flush_or_wait_ms") is not None
                        else None
                    )
                    hid_ack_arrival_ms = (
                        float(timing.get("ack_arrival_ms"))  # type: ignore[arg-type]
                        if isinstance(timing, dict) and timing.get("ack_arrival_ms") is not None
                        else None
                    )
                    hid_flush_or_wait_reason = str(
                        timing.get("flush_or_wait_reason", hid_flush_or_wait_reason)
                    )
                    hid_frame_build_reason = "Measured inside driver send path."
                    hid_device_limited_label = (
                        "yes" if bool(timing.get("device_limited", False)) else "no"
                    )
                    hid_reports_per_frame = str(timing.get("reports_per_frame", "unavailable"))
                    hid_bytes_per_report = str(timing.get("bytes_per_report", "unavailable"))
                    hid_total_frame_bytes = str(timing.get("total_frame_bytes", "unavailable"))
                    report_data_sizes = timing.get("report_data_sizes")
                    hid_report_data_sizes = (
                        ",".join(str(int(v)) for v in report_data_sizes)
                        if isinstance(report_data_sizes, list)
                        else "unavailable"
                    )
                    per_report_write_ms = timing.get("per_report_write_ms")
                    hid_per_report_write_ms = (
                        ",".join(f"{float(v):.3f}" for v in per_report_write_ms)
                        if isinstance(per_report_write_ms, list)
                        else "unavailable"
                    )
                    hid_write_blocking = "yes" if bool(timing.get("write_blocking", True)) else "no"
                    hid_write_retry_policy = str(timing.get("write_retry_policy", "none"))
                    hid_write_rate_limit_policy = str(timing.get("write_rate_limit_policy", "none"))
                    hid_write_read_calls = str(timing.get("write_read_calls", "unavailable"))
                    hid_live_send_policy = str(timing.get("live_send_policy", "response_required"))
                    hid_response_wait_skipped = (
                        "yes" if bool(timing.get("response_wait_skipped", False)) else "no"
                    )
                else:
                    driver.send_frame(payload.smoothed_colors)

                send_done = time.perf_counter()
                hid_write_ms = (send_done - hid_write_start) * 1000.0
                send_interval_s = 1.0 / float(pace_fps)
                next_send_deadline_ts = send_done + send_interval_s
                if hid_device_write_ms is None:
                    hid_device_write_ms = hid_write_ms

                frame_processing_ms = (
                    (payload.processing_timings.frame_convert_ms or 0.0)  # type: ignore[attr-defined]
                    + (payload.processing_timings.zone_sampling_ms or 0.0)  # type: ignore[attr-defined]
                    + (payload.processing_timings.colour_processing_ms or 0.0)  # type: ignore[attr-defined]
                    + (payload.processing_timings.smoothing_ms or 0.0)  # type: ignore[attr-defined]
                    + (payload.processing_timings.led_calibration_ms or 0.0)  # type: ignore[attr-defined]
                    + (payload.processing_timings.output_prepare_ms or 0.0)  # type: ignore[attr-defined]
                )
                actual_work_ms = (send_done - now) * 1000.0
                loop_gap_ms = (
                    (send_done - last_send_done_ts) * 1000.0
                    if last_send_done_ts is not None
                    else None
                )
                if loop_gap_ms is not None:
                    hid_loop_gap_ewma_ms = (
                        (0.9 * hid_loop_gap_ewma_ms) + (0.1 * loop_gap_ms)
                        if hid_loop_gap_ewma_ms is not None
                        else float(loop_gap_ms)
                    )
                inferred_unattributed_gap_ms = (
                    max(0.0, loop_gap_ms - actual_work_ms) if loop_gap_ms is not None else None
                )

                pace_fps = min(
                    max(1, int(getattr(config, "fps", 60))),
                    max(1, int(governor.target_fps)),
                )
                frame_budget_ms = 1000.0 / float(pace_fps)
                output_cycle_ms = float(actual_work_ms)
                hid_output_work_ewma_ms = (
                    (0.9 * hid_output_work_ewma_ms) + (0.1 * output_cycle_ms)
                    if hid_output_work_ewma_ms is not None
                    else float(output_cycle_ms)
                )

                with metrics_lock:
                    cap_active = bool(capture_worker_active)
                    cap_error_now = int(capture_worker_error_count)

                pending_frame_age_ms = max(
                    0.0,
                    (time.perf_counter() - payload.captured_at) * 1000.0,
                )
                capture_to_send_ms = (send_done - payload.captured_at) * 1000.0
                ewma_capture_to_send_ms = (
                    (0.9 * ewma_capture_to_send_ms) + (0.1 * capture_to_send_ms)
                    if ewma_capture_to_send_ms > 0.0
                    else capture_to_send_ms
                )

                with metrics_lock:
                    no_pending_events = no_pending_frame_events
                capture_dropped_delta = capture_buf.dropped_count()
                capture_buf.reset_dropped()
                process_dropped_delta = process_buf.dropped_count()
                process_buf.reset_dropped()
                dropped_delta = capture_dropped_delta + process_dropped_delta + coalesced_sends

                state.latency_probe.add_stage_sample(
                    FrameTimingSample(
                        stage_ms={
                            STAGE_CAPTURE_CALL: capture_call_ms_latest,
                            STAGE_RUNTIME_CAPTURE_CALL: capture_call_ms_latest,
                            STAGE_CAPTURE_WORKER_LOOP_GAP: capture_worker_loop_gap_ms_latest,
                            STAGE_CAPTURE_SUCCESS_INTERVAL: capture_success_interval_ms_latest,
                            STAGE_FRAME_HANDOFF_WAIT: None,
                            STAGE_FRAME_AVAILABLE_WAIT: None,
                            STAGE_PENDING_FRAME_AGE: pending_frame_age_ms,
                            STAGE_IDLE_WAIT: None,
                            STAGE_RUNTIME_IDLE_WAIT: None,
                            STAGE_FRAME_PROCESSING: frame_processing_ms,
                            STAGE_FRAME_CONVERT: payload.processing_timings.frame_convert_ms,  # type: ignore[attr-defined]
                            STAGE_ZONE_SAMPLING: payload.processing_timings.zone_sampling_ms,  # type: ignore[attr-defined]
                            STAGE_COLOUR_PROCESSING: (
                                payload.processing_timings.colour_processing_ms
                            ),  # type: ignore[attr-defined]
                            STAGE_SMOOTHING: payload.processing_timings.smoothing_ms,  # type: ignore[attr-defined]
                            STAGE_LED_CALIBRATION: payload.processing_timings.led_calibration_ms,  # type: ignore[attr-defined]
                            STAGE_OUTPUT_PREPARE: payload.processing_timings.output_prepare_ms,  # type: ignore[attr-defined]
                            STAGE_ACTUAL_WORK: actual_work_ms,
                            STAGE_HID_WRITE: hid_write_ms,
                            STAGE_HID_FRAME_BUILD: hid_frame_build_ms,
                            STAGE_HID_DEVICE_WRITE: hid_device_write_ms,
                            STAGE_HID_FLUSH_OR_WAIT: hid_flush_or_wait_ms,
                            STAGE_HID_ACK_ARRIVAL: hid_ack_arrival_ms,
                            STAGE_LOOP_GAP: loop_gap_ms,
                            STAGE_INFERRED_UNATTRIBUTED_GAP: inferred_unattributed_gap_ms,
                            STAGE_END_TO_END_LIVE: capture_to_send_ms,
                        },
                        target_fps=float(governor.target_fps),
                        fps_cap=float(governor.target_fps),
                        fps_cap_reason="FPS governor dynamic cap",
                        dropped_or_skipped_frames_delta=dropped_delta,
                        counters_delta={
                            "capture_worker_error_count": max(0, cap_error_now),
                            "capture_buffer_dropped_frames": capture_dropped_delta,
                            "process_buffer_dropped_frames": process_dropped_delta,
                            "coalesced_sends": coalesced_sends,
                        },
                        flags={"capture_worker_active": cap_active},
                        labels={
                            "latest_capture_backend_name": latest_capture_backend_name,
                            "capture_backend_method": latest_capture_backend_method,
                            **_frame_context_latency_labels(payload),
                            "no_pending_frame_rate_per_second": _no_pending_frame_rate_per_second(
                                no_pending_events, no_pending_started_at
                            ),
                            "hid_flush_or_wait_reason": hid_flush_or_wait_reason,
                            "hid_frame_build_reason": hid_frame_build_reason,
                            "hid_device_write_limited": hid_device_limited_label,
                            "hid_reports_per_frame": hid_reports_per_frame,
                            "hid_bytes_per_report": hid_bytes_per_report,
                            "hid_total_frame_bytes": hid_total_frame_bytes,
                            "hid_report_data_sizes": hid_report_data_sizes,
                            "hid_per_report_write_ms": hid_per_report_write_ms,
                            "hid_write_blocking": hid_write_blocking,
                            "hid_write_retry_policy": hid_write_retry_policy,
                            "hid_write_rate_limit_policy": hid_write_rate_limit_policy,
                            "hid_write_read_calls": hid_write_read_calls,
                            "hid_live_send_policy": hid_live_send_policy,
                            "hid_response_wait_skipped": hid_response_wait_skipped,
                        },
                    )
                )

                state.record_success()
                if payload.smooth_float_history:
                    state.prev_smooth_float_colors = [
                        tuple(float(c) for c in row) for row in payload.smooth_float_history
                    ]
                state.prev_sent_colors = [
                    tuple(int(c) for c in row) for row in payload.smoothed_colors
                ]
                state.prev_smoothed_colors = list(state.prev_sent_colors)
                state.first_frame_sent = True
                state.startup_elapsed_ms = max(
                    0.0,
                    (time.perf_counter() - startup_started_at) * 1000.0,
                )
                if not state.startup_complete.is_set():
                    state.start_failure_reason = ""
                    state.lifecycle_state = "running"
                    state.mark_startup(True)
                last_sent_zone_count = len(payload.smoothed_colors)
                sent_in_window += 1

                # ---- adaptive FPS governor -----------------------------
                previous_target = governor.target_fps
                governor.record_frame(capture_to_send_ms)
                with gov_lock:
                    state.target_fps = governor.target_fps
                state.governor_p95_latency_ms = float(
                    governor.get_metrics().get("p95_latency_ms", 0.0) or 0.0
                )
                state.latest_staleness_ms = float(capture_to_send_ms)
                state.output_healthy = output_cycle_ms <= (frame_budget_ms * 1.1)
                if governor.target_fps != previous_target:
                    direction = "up" if governor.target_fps > previous_target else "down"
                    logger.info(
                        "FPS governor: stepped %s %d → %d (p95_latency_ms=%.2f)",
                        direction,
                        previous_target,
                        governor.target_fps,
                        governor.get_metrics()["p95_latency_ms"],
                    )
                    if config.verbose:
                        print(
                            f"[service] FPS governor: stepped {direction} "
                            f"{previous_target} → {governor.target_fps} "
                            f"(p95_latency_ms={governor.get_metrics()['p95_latency_ms']:.2f})"
                        )

                # ---- adaptive pacing -----------------------------------
                budget_ms = frame_budget_ms
                pacing_wait_s = max(0.0, budget_ms / 1000.0 - actual_work_ms)
                if pacing_wait_s > 0.0:
                    time.sleep(pacing_wait_s)
                last_send_done_ts = time.perf_counter()

                # Periodic status log
                if now - last_log > log_interval_s:
                    window_s = max(0.001, now - last_log)
                    send_fps_val = sent_in_window / window_s
                    dropped_total = capture_buf.dropped_count()
                    last_log = now
                    sent_in_window = 0
                    logger.info(
                        "service_tick seq=%s fps=%s elapsed_ms=%.2f "
                        "zones=%s errors=%s send_fps=%.1f "
                        "capture_to_send_ms=%.2f dropped_frames=%s",
                        frame_seq,
                        governor.target_fps,
                        actual_work_ms,
                        last_sent_zone_count,
                        state.consecutive_errors,
                        send_fps_val,
                        ewma_capture_to_send_ms,
                        dropped_total,
                    )
                    if config.verbose:
                        print(
                            f"[service] tick fps={governor.target_fps} "
                            f"elapsed_ms={actual_work_ms:.2f} "
                            f"zones={last_sent_zone_count} "
                            f"send_fps={send_fps_val:.1f} "
                            f"capture_to_send_ms={ewma_capture_to_send_ms:.2f} "
                            f"dropped_frames={dropped_total}"
                        )
            except Exception as exc:
                state.record_error(exc)
                logger.debug("HID writer error: %s", exc)

    # ---- start threads --------------------------------------------------
    threads = [
        threading.Thread(target=_capture_worker, name="capture-worker", daemon=True),
        threading.Thread(target=_process_worker, name="process-worker", daemon=True),
        threading.Thread(target=_hid_writer, name="hid-writer", daemon=True),
    ]
    for t in threads:
        t.start()

    # ---- supervisory loop ------------------------------------------------
    time.perf_counter()
    last_reinit_check = time.perf_counter()
    while not state.stop_event.is_set():
        time.sleep(0.05)
        now = time.perf_counter()

        # Startup timeout
        if not state.first_frame_sent and not state.startup_complete.is_set():
            startup_elapsed = now - startup_started_at
            state.startup_elapsed_ms = max(0.0, startup_elapsed * 1000.0)
            if startup_elapsed >= startup_frame_timeout_s:
                backend = latest_capture_backend_name or "unavailable"
                method = latest_capture_backend_method or "unavailable"
                if state.first_frame_seen and int(state.output_owner_dropped_frames) > 0:
                    reason = (
                        "Start failed before first frame: mirroring output is blocked "
                        f"(backend={backend}, method={method}). "
                        "Close Settings/setup preview and retry Start."
                    )
                    guidance = (
                        "Another exclusive LED output session is active, or mirroring "
                        "authorization expired after Stop. Press Start again after "
                        "closing setup tools."
                    )
                else:
                    reason = (
                        "Start failed before first frame: capture backend "
                        f"produced no frame within {startup_frame_timeout_s:.1f}s "
                        f"(backend={backend}, method={method})."
                    )
                    guidance = "Check capture backend readiness and retry."
                state.last_error = reason
                state.last_error_kind = "capture-timeout"
                state.last_error_guidance = guidance
                state.start_failure_reason = reason
                state.lifecycle_state = "failed"
                state.mark_startup(False)
                state.stop_event.set()
                break

        # Reinitialization check
        if now - last_reinit_check > 0.5:
            last_reinit_check = now
            with metrics_lock:
                worker_fails = capture_worker_failures
                proc_fails = process_worker_error_count
            if worker_fails >= error_limit or proc_fails >= error_limit:
                logger.warning(
                    "worker failures: capture=%d process=%d (limit=%d); "
                    "triggering reinitialization",
                    worker_fails,
                    proc_fails,
                    error_limit,
                )
                backoff_s = max(
                    0.0,
                    float(getattr(config, "reinit_backoff_ms", 500)) / 1000.0,
                )
                if should_reinitialize(
                    state=state,
                    error_limit=error_limit,
                    backoff_s=backoff_s,
                    now_ts=now,
                ):
                    reinitialize_backends(
                        install_drivers=install_drivers,
                        close_backends=close_backends,
                        state=state,
                    )
                    _clear_pipeline_temporal_state(
                        state=state,
                        capture_buf=capture_buf,
                        process_buf=process_buf,
                        metadata_tracker=metadata_tracker,
                    )
                    with metrics_lock:
                        capture_worker_failures = 0
                        capture_worker_error_count = 0
                        process_worker_error_count = 0
            sustained_black_frames = 120
            if (
                state.consecutive_black_frames >= sustained_black_frames
                and state.consecutive_black_frames % sustained_black_frames == 0
            ):
                backoff_s = max(
                    0.0,
                    float(getattr(config, "reinit_backoff_ms", 500)) / 1000.0,
                )
                if should_reinitialize(
                    state=state,
                    error_limit=error_limit,
                    backoff_s=backoff_s,
                    now_ts=now,
                ):
                    logger.warning(
                        "Sustained all-black capture (%d frames); reinitializing backends",
                        state.consecutive_black_frames,
                    )
                    reinitialize_backends(
                        install_drivers=install_drivers,
                        close_backends=close_backends,
                        state=state,
                    )
                    _clear_pipeline_temporal_state(
                        state=state,
                        capture_buf=capture_buf,
                        process_buf=process_buf,
                        metadata_tracker=metadata_tracker,
                    )
                    state.consecutive_black_frames = 0
    for t in threads:
        t.join(timeout=3.0)
        if t.is_alive():
            logger.warning(
                "%s thread did not exit within shutdown timeout (3s); "
                "it may still be blocked in IO",
                t.name,
            )

    capture_dropped_delta = capture_buf.dropped_count()
    capture_buf.reset_dropped()
    process_dropped_delta = process_buf.dropped_count()
    process_buf.reset_dropped()
    dropped_delta = capture_dropped_delta + process_dropped_delta
    if dropped_delta > 0:
        state.latency_probe.add_stage_sample(
            FrameTimingSample(
                stage_ms={},
                target_fps=float(governor.target_fps),
                fps_cap=float(governor.target_fps),
                fps_cap_reason="FPS governor dynamic cap",
                dropped_or_skipped_frames_delta=dropped_delta,
                counters_delta={
                    "capture_buffer_dropped_frames": capture_dropped_delta,
                    "process_buffer_dropped_frames": process_dropped_delta,
                },
            )
        )


def run_loop(
    *,
    config: AppConfig,
    state: RuntimeState,
    get_capture,
    get_driver,
    install_drivers,
    close_backends,
    use_legacy_pipeline: bool = False,
    can_mirroring_write: Callable[[], bool] | None = None,
) -> None:
    """Entry point for the mirroring 3-stage pipeline runtime loop."""
    if use_legacy_pipeline:
        logger.warning(
            "use_legacy_pipeline is deprecated and ignored; the 3-stage pipeline is always used."
        )
    _run_loop_pipeline(
        config=config,
        state=state,
        get_capture=get_capture,
        get_driver=get_driver,
        install_drivers=install_drivers,
        close_backends=close_backends,
        can_mirroring_write=can_mirroring_write,
    )
