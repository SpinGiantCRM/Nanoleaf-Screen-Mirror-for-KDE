"""Frame processing helpers and process_frame for the mirroring runtime."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from nanoleaf_sync.color._types import RGBTuple
from nanoleaf_sync.color.metadata_hysteresis import MetadataHysteresisTracker
from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.runtime.blending import (
    AdaptiveSmoothingDiagnostics,
    BlendHysteresisState,
    adaptive_one_euro_blend,
    apply_neighbor_blend,
)
from nanoleaf_sync.runtime.calibration_resolver import (
    CALIBRATION_READY_STATUS,
    resolve_calibration_mapping_from_config,
)
from nanoleaf_sync.runtime.color_pipeline import (
    ColorPipelineParams,
    process_zone_colors,
)
from nanoleaf_sync.runtime.color_processing import (
    LedCalibration,
    init_gamut_adaptation,
)
from nanoleaf_sync.runtime.fps_governor import (
    FPSGovernor,
    governor_min_fps_floor,
)
from nanoleaf_sync.runtime.frame_context import FrameContext
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.runtime.ring_buf import (
    ProcessedPayload,
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
    blend_hysteresis: BlendHysteresisState | None = None
    output_quantization_prev_hold: tuple[bool, ...] = ()
    colour_path_before_style: tuple[tuple[int, int, int], ...] = ()
    colour_path_after_style: tuple[tuple[int, int, int], ...] = ()
    colour_path_after_spread: tuple[tuple[int, int, int], ...] = ()
    colour_path_after_smoothing: tuple[tuple[int, int, int], ...] = ()
    colour_path_after_led_calibration: tuple[tuple[int, int, int], ...] = ()
    colour_path_final: tuple[tuple[int, int, int], ...] = ()
    per_zone_variance: tuple[float, ...] = ()


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
    blended, diagnostics, _updated = adaptive_one_euro_blend(
        current=current,
        previous=previous,
        smoothing=smoothing,
        smoothing_speed=smoothing_speed,
        motion_preset=motion_preset,
    )
    return blended, diagnostics


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
    zones: Sequence[ZoneConfig],
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

    raw_side_counts = zone_artifacts.side_counts or (0, 0, 0, 0)
    state.latest_zone_side_counts = (
        (
            int(raw_side_counts[0]),
            int(raw_side_counts[1]),
            int(raw_side_counts[2]),
            int(raw_side_counts[3]),
        )
        if len(raw_side_counts) >= 4
        else (0, 0, 0, 0)
    )
    state.latest_edge_sampling_thickness = zone_artifacts.edge_sampling_thickness
    return zones_px, state.cached_device_zone_indices_np


def _apply_neighbor_blend(mapped: np.ndarray, *, spread_mode: str) -> np.ndarray:
    blended = apply_neighbor_blend(mapped, spread_mode=spread_mode)
    if isinstance(blended, tuple):
        return blended[0]
    return blended


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


def _capture_backend_display_referred(
    capture_backend_name: str,
    cap_backend: object | None,
) -> bool:
    capture_display_referred = capture_backend_name in {
        "kwin-dbus",
        "xdg-portal",
    }
    if cap_backend is not None and capture_backend_name == "kmsgrab":
        drm_sampler = getattr(cap_backend, "_drm_zone_sampler", None)
        if drm_sampler is not None and bool(getattr(drm_sampler, "is_10bit", False)):
            capture_display_referred = True
    if cap_backend is not None:
        hdr_diag = getattr(cap_backend, "last_hdr_diagnostics", None) or {}
        if isinstance(hdr_diag, dict):
            capture_display_referred = (
                capture_display_referred
                or bool(hdr_diag.get("display_referred", False))
                or bool(hdr_diag.get("tone_mapping_applied", False))
            )
    return capture_display_referred


_SHORT_BLACK_HOLD_MAX_FRAMES = 5
_CAPTURE_CONTINUITY_GAP_S = 0.5


def _reset_pipeline_state(
    *,
    state: RuntimeState,
    reason: str,
    metadata_tracker: MetadataHysteresisTracker | None = None,
    buffers: bool = True,
) -> None:
    """Clear temporal pipeline state when capture continuity or identity changes."""
    logger.info("Pipeline state reset: %s", reason)
    state.clear_smoothing_history()
    if buffers:
        state.smoothing_dimension_signature = None
        state.request_pipeline_buffer_clear()
        if metadata_tracker is not None:
            metadata_tracker.reset()


def process_frame(
    *,
    frame: np.ndarray | None,
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
    prev_smooth_float_colors: Sequence[tuple[float, float, float]] = (),
    prev_sent_colors: Sequence[RGBTuple] = (),
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
    smooth_history: Sequence[tuple[float, float, float]] = (
        prev_smooth_float_colors
        if prev_smooth_float_colors
        else [(float(r), float(g), float(b)) for r, g, b in prev_smoothed_colors]
    )
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
