"""Frame-processing engine for the mirroring runtime loop.

The functions in this module transform captured RGB frames into device-zone
colors, apply brightness/smoothing, and handle runtime reinitialization hooks.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from nanoleaf_sync.capture.latency_probe import (
    STAGE_ACTUAL_WORK,
    STAGE_CAPTURE_CALL,
    STAGE_CAPTURE_SUCCESS_INTERVAL,
    STAGE_CAPTURE_WAIT,
    STAGE_CAPTURE_WORKER_LOOP_GAP,
    STAGE_COLOUR_PROCESSING,
    STAGE_FRAME_AVAILABLE_WAIT,
    STAGE_FRAME_CONVERT,
    STAGE_FRAME_HANDOFF_WAIT,
    STAGE_FRAME_PROCESSING,
    STAGE_HID_DEVICE_WRITE,
    STAGE_HID_FLUSH_OR_WAIT,
    STAGE_HID_FRAME_BUILD,
    STAGE_HID_WRITE,
    STAGE_IDLE_WAIT,
    STAGE_INFERRED_UNATTRIBUTED_GAP,
    STAGE_LED_CALIBRATION,
    STAGE_LOOP_GAP,
    STAGE_OUTPUT_PREPARE,
    STAGE_PACING_WAIT,
    STAGE_PENDING_FRAME_AGE,
    STAGE_RUNTIME_CAPTURE_CALL,
    STAGE_RUNTIME_IDLE_WAIT,
    STAGE_SMOOTHING,
    STAGE_ZONE_SAMPLING,
    FrameTimingSample,
)
from nanoleaf_sync.color._types import RGBTuple
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.blending import (
    AdaptiveSmoothingDiagnostics,
    adaptive_one_euro_blend,
    apply_neighbor_blend,
)
from nanoleaf_sync.runtime.calibration_resolver import (
    CALIBRATION_INCOMPLETE_MESSAGE,
    CALIBRATION_INCOMPLETE_STATUS,
    CALIBRATION_READY_STATUS,
    resolve_calibration_mapping_from_config,
)
from nanoleaf_sync.runtime.color_pipeline import (
    ColorPipelineParams,
    build_pipeline_params_from_config,
    process_zone_colors,
    zone_centers_from_zones_px,
)
from nanoleaf_sync.runtime.color_processing import (
    LedCalibration,
    color_pipeline_diagnostics,
    init_gamut_adaptation,
)
from nanoleaf_sync.runtime.fps_governor import FPSGovernor
from nanoleaf_sync.runtime.processing import scale_zones_to_display, zones_from_config
from nanoleaf_sync.runtime.ring_buf import (
    CapturePayload,
    ProcessedPayload,
    SPSCRingBuffer,
)
from nanoleaf_sync.runtime.startup import reinitialize_backends, should_reinitialize
from nanoleaf_sync.runtime.state import (
    DeviceZoneMappingSignature,
    RuntimeState,
    ZoneRect,
)
from nanoleaf_sync.runtime.zone_derivation import derive_source_zone_artifacts

logger = logging.getLogger(__name__)


def _gamut_init_from_config(config: AppConfig) -> None:
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
    edge_locality: str = "tight",
    sampling_mode: str = "auto",
    letterbox_detection: bool = True,
    compositor_hdr_mode: bool = False,
    sdr_boost_nits: float = 80.0,
    hdr_max_nits: float = 1000.0,
    accuracy_mode: bool = False,
    skip_display_gamut_adaptation: bool = False,
    precomputed_zone_colors: np.ndarray | None = None,
    return_diagnostics: bool = False,
    build_zone_diagnostics: bool = False,
    led_calibration: LedCalibration | None = None,
) -> (
    list[RGBTuple]
    | tuple[list[RGBTuple], np.ndarray, np.ndarray, np.ndarray, FrameProcessingTimings]
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
        accuracy_mode=accuracy_mode,
        skip_display_gamut_adaptation=skip_display_gamut_adaptation,
        led_calibration=calibration,
        return_diagnostics=return_diagnostics,
        build_zone_diagnostics=build_zone_diagnostics,
    )
    return process_zone_colors(
        frame=frame if precomputed_zone_colors is None else None,
        precomputed_zone_colors=precomputed_zone_colors,
        prev_smoothed_colors=prev_smoothed_colors,
        zones_px=zones_px,
        device_zone_indices=device_zone_indices,
        params=params,
    )


def _run_loop_legacy(
    *,
    config: AppConfig,
    state: RuntimeState,
    get_capture,
    get_driver,
    install_drivers,
    close_backends,
) -> None:
    _gamut_init_from_config(config)
    fps = max(1, int(config.fps))
    governor = FPSGovernor(initial_fps=fps)
    state.target_fps = governor.target_fps
    interval_s = 1.0 / fps

    next_deadline = time.perf_counter()
    last_log = 0.0
    log_interval_s = float(getattr(config, "status_log_interval_s", 5.0))
    last_sent_zone_count = 0
    sent_in_window = 0
    sent_any_frame = False
    ewma_capture_to_send_ms = 0.0
    last_send_done_ts: float | None = None
    last_pacing_wait_ms: float | None = None
    last_replaced_count = 0
    frame_seq: int = 0

    pending_slot = PendingFrameSlot()
    capture_worker_lock = threading.Lock()
    capture_worker_error: Exception | None = None
    capture_worker_failures = 0
    capture_worker_error_count = 0
    capture_worker_active = False
    capture_call_ms_latest: float | None = None
    capture_worker_loop_gap_ms_latest: float | None = None
    capture_success_interval_ms_latest: float | None = None
    last_capture_completed_ts: float | None = None
    last_capture_success_ts: float | None = None
    latest_capture_backend_name = "unavailable"
    latest_capture_backend_method = ""
    no_pending_frame_ticks = 0
    no_pending_frame_events = 0
    no_pending_started_at = time.perf_counter()
    last_reported_capture_worker_error_count = 0
    startup_started_at = time.perf_counter()
    startup_frame_timeout_s = max(0.1, float(getattr(config, "startup_frame_timeout_s", 5.0)))

    def _capture_worker() -> None:
        nonlocal capture_worker_error, capture_worker_failures, capture_worker_error_count
        nonlocal capture_worker_active, capture_call_ms_latest, capture_worker_loop_gap_ms_latest
        nonlocal \
            capture_success_interval_ms_latest, \
            last_capture_completed_ts, \
            last_capture_success_ts
        nonlocal latest_capture_backend_name, latest_capture_backend_method
        with capture_worker_lock:
            capture_worker_active = True
        while not state.stop_event.is_set():
            state.reinit_pause.wait(timeout=0.001)
            try:
                if state.is_reinitializing:
                    time.sleep(0.001)
                    continue
                capture = get_capture()
                if capture is None:
                    time.sleep(0.001)
                    continue
                if pending_slot.has_pending():
                    time.sleep(0.0005)
                    continue
                latest_capture_backend_name = str(getattr(capture, "name", "unknown"))
                latest_capture_backend_method = str(getattr(capture, "last_capture_path", "") or "")
                capture_start = time.perf_counter()
                frame = capture.capture()
                capture_end = time.perf_counter()
                call_ms = (capture_end - capture_start) * 1000.0
                with capture_worker_lock:
                    capture_call_ms_latest = call_ms
                    if last_capture_completed_ts is not None:
                        capture_worker_loop_gap_ms_latest = (
                            capture_end - last_capture_completed_ts
                        ) * 1000.0
                    last_capture_completed_ts = capture_end
                if frame is None:
                    continue
                with capture_worker_lock:
                    if last_capture_success_ts is not None:
                        capture_success_interval_ms_latest = (
                            capture_end - last_capture_success_ts
                        ) * 1000.0
                    last_capture_success_ts = capture_end
                pending_slot.put_latest(frame=frame, captured_at=capture_end)
                with capture_worker_lock:
                    capture_worker_error = None
                    capture_worker_failures = 0
            except Exception as exc:
                with capture_worker_lock:
                    capture_worker_failures += 1
                    capture_worker_error_count += 1
                    capture_worker_error = exc
                logger.debug("capture worker error", exc_info=True)
                time.sleep(0.005)
        with capture_worker_lock:
            capture_worker_active = False

    capture_thread = threading.Thread(target=_capture_worker, name="capture-worker", daemon=True)
    capture_thread.start()

    while True:
        stop_requested = state.stop_event.is_set()
        start = time.perf_counter()
        processing_end = start
        send_done = start
        skip_tick = False
        capture_wait_ms: float | None = None
        idle_wait_ms: float | None = None
        pacing_wait_ms: float | None = last_pacing_wait_ms
        frame_handoff_wait_ms: float | None = None
        pending_frame_age_ms: float | None = None
        frame = None
        pending = None

        try:
            if stop_requested:
                break
            error_limit = max(1, int(getattr(config, "max_consecutive_errors", 5)))

            if state.is_reinitializing:
                if stop_requested:
                    break
                skip_tick = True
            else:
                with capture_worker_lock:
                    worker_error = capture_worker_error
                    worker_failures = capture_worker_failures
                    if worker_error is not None and worker_failures >= error_limit:
                        capture_worker_error = None
                        capture_worker_failures = 0
                if worker_error is not None and worker_failures >= error_limit:
                    raise RuntimeError(
                        f"capture worker failed {worker_failures} consecutive attempts"
                    ) from worker_error

                driver = get_driver()
                if driver is None:
                    if stop_requested:
                        break
                    skip_tick = True
                else:
                    if stop_requested and sent_any_frame:
                        break
                    pending = pending_slot.pop()
                    if pending is None and not stop_requested:
                        wait_budget = max(
                            0.0,
                            min(interval_s, next_deadline - time.perf_counter()),
                        )
                        wait_start = time.perf_counter()
                        pending_slot.wait(timeout=min(0.005, wait_budget))
                        wait_end = time.perf_counter()
                        idle_wait_ms = (wait_end - wait_start) * 1000.0
                        frame_handoff_wait_ms = idle_wait_ms
                        pending = pending_slot.pop()
                    if pending is None:
                        no_pending_frame_ticks += 1
                        no_pending_frame_events += 1
                        if stop_requested:
                            break
                        skip_tick = True
                        frame_handoff_wait_ms = idle_wait_ms
                    else:
                        frame = pending.frame
                        captured_at = pending.captured_at
                        state.first_frame_seen = True
                        pending_frame_age_ms = max(
                            0.0, (time.perf_counter() - captured_at) * 1000.0
                        )

            if skip_tick:
                with capture_worker_lock:
                    capture_worker_active_now = bool(capture_worker_active)
                    capture_worker_error_count_now = int(capture_worker_error_count)
                state.latency_probe.add_stage_sample(
                    FrameTimingSample(
                        stage_ms={
                            STAGE_CAPTURE_WAIT: capture_wait_ms,
                            STAGE_CAPTURE_CALL: capture_call_ms_latest,
                            STAGE_RUNTIME_CAPTURE_CALL: capture_call_ms_latest,
                            STAGE_CAPTURE_WORKER_LOOP_GAP: capture_worker_loop_gap_ms_latest,
                            STAGE_CAPTURE_SUCCESS_INTERVAL: capture_success_interval_ms_latest,
                            STAGE_FRAME_HANDOFF_WAIT: frame_handoff_wait_ms,
                            STAGE_FRAME_AVAILABLE_WAIT: frame_handoff_wait_ms,
                            STAGE_PENDING_FRAME_AGE: pending_frame_age_ms,
                            STAGE_PACING_WAIT: pacing_wait_ms,
                            STAGE_IDLE_WAIT: idle_wait_ms,
                            STAGE_RUNTIME_IDLE_WAIT: idle_wait_ms,
                            STAGE_FRAME_PROCESSING: None,
                            STAGE_ACTUAL_WORK: None,
                            STAGE_LOOP_GAP: None,
                        },
                        target_fps=float(governor.target_fps),
                        fps_cap=float(governor.target_fps),
                        fps_cap_reason="FPS governor dynamic cap",
                        dropped_or_skipped_frames_delta=0,
                        counters_delta={
                            "no_pending_frame_ticks": no_pending_frame_ticks,
                            "capture_errors_retries": max(
                                0,
                                capture_worker_error_count_now
                                - last_reported_capture_worker_error_count,
                            ),
                            "capture_worker_error_count": max(
                                0,
                                capture_worker_error_count_now
                                - last_reported_capture_worker_error_count,
                            ),
                        },
                        flags={"capture_worker_active": capture_worker_active_now},
                        labels={
                            "latest_capture_backend_name": latest_capture_backend_name,
                            "capture_backend_method": latest_capture_backend_method,
                            "no_pending_frame_rate_per_second": _no_pending_frame_rate_per_second(
                                no_pending_frame_events, no_pending_started_at
                            ),
                        },
                    )
                )
                last_reported_capture_worker_error_count = capture_worker_error_count_now
                no_pending_frame_ticks = 0
            else:
                if frame is None:
                    raise ValueError("capture returned None frame")
                img_h, img_w, _ = frame.shape
                zones_px, device_zone_indices = _ensure_runtime_artifacts(
                    state=state,
                    config=config,
                    img_w=img_w,
                    img_h=img_h,
                    detected_device_zone_count=getattr(
                        driver,
                        "reported_zone_count",
                        getattr(driver, "zone_count", None),
                    ),
                )

                if (
                    state.calibration_status == CALIBRATION_INCOMPLETE_STATUS
                    or len(device_zone_indices) <= 0
                ):
                    message = state.calibration_status_message or CALIBRATION_INCOMPLETE_MESSAGE
                    if len(device_zone_indices) <= 0 and "empty" not in message.lower():
                        message = f"{message} Derived device-zone mapping is empty."
                    state.mark_calibration_incomplete(message)
                    state.startup_elapsed_ms = max(
                        0.0, (time.perf_counter() - startup_started_at) * 1000.0
                    )
                    state.mark_startup(False)
                    state.stop_event.set()
                    logger.warning(
                        "calibration incomplete; screen mirroring will not stream frames: %s",
                        message,
                    )
                    break

                active_profile = (
                    getattr(config, "led_calibration_profile_sdr", None)
                    if str(getattr(config, "display_preset", "hdr")).strip().lower() == "sdr"
                    else getattr(config, "led_calibration_profile_hdr", None)
                )
                frame_seq += 1
                processed = process_frame(
                    frame=frame,
                    prev_smoothed_colors=state.prev_smoothed_colors,
                    zones_px=zones_px,
                    device_zone_indices=device_zone_indices,
                    brightness=config.brightness,
                    smoothing=config.smoothing,
                    smoothing_speed=config.smoothing_speed,
                    zone_sampling_stride=config.zone_sampling_stride,
                    zone_sampling_engine=getattr(config, "zone_sampling_engine", "auto"),
                    led_gamma=float(getattr(active_profile, "led_gamma", config.led_gamma)),
                    motion_preset=getattr(config, "motion_preset", "responsive"),
                    light_spread=getattr(config, "light_spread", "balanced"),
                    red_gain=float(
                        getattr(active_profile, "red_gain", getattr(config, "red_gain", 1.0))
                    ),
                    green_gain=float(
                        getattr(active_profile, "green_gain", getattr(config, "green_gain", 1.0))
                    ),
                    blue_gain=float(
                        getattr(active_profile, "blue_gain", getattr(config, "blue_gain", 1.0))
                    ),
                    white_balance_temperature=float(
                        getattr(
                            active_profile,
                            "white_balance_temperature",
                            getattr(config, "white_balance_temperature", 0.0),
                        )
                    ),
                    chroma_compression=float(
                        getattr(
                            active_profile,
                            "chroma_compression",
                            getattr(config, "chroma_compression", 0.0),
                        )
                    ),
                    neutral_luminance_gain=float(
                        getattr(
                            active_profile,
                            "neutral_luminance_gain",
                            getattr(config, "neutral_luminance_gain", 1.0),
                        )
                    ),
                    black_luminance_cutoff=float(
                        getattr(
                            active_profile,
                            "black_luminance_cutoff",
                            getattr(config, "black_luminance_cutoff", 0.0032),
                        )
                    ),
                    black_luminance_knee=float(
                        getattr(
                            active_profile,
                            "black_luminance_knee",
                            getattr(config, "black_luminance_knee", 0.0024),
                        )
                    ),
                    color_style=getattr(config, "color_style", "natural"),
                    edge_locality=getattr(config, "edge_locality", "balanced"),
                    compositor_hdr_mode=getattr(config, "compositor_hdr_mode", False),
                    sdr_boost_nits=getattr(config, "sdr_boost_nits", 80.0),
                    hdr_max_nits=getattr(config, "hdr_max_nits", 1000.0),
                    return_diagnostics=True,
                )
                (
                    smoothed_colors,
                    sampled_zone_colors,
                    pre_led_colors,
                    final_zone_colors,
                    processing_timings,
                ) = processed
                processing_end = time.perf_counter()
                state.prev_smoothed_colors = smoothed_colors
                state.first_frame_processed = True
                state.last_frame_width = int(img_w)
                state.last_frame_height = int(img_h)
                state.latest_frame_rgb = frame
                state.latest_zones_px = list(zones_px)
                zone_diagnostics: list[dict[str, object]] = []
                for zone_index, rect in enumerate(zones_px):
                    sampled_rgb = tuple(int(c) for c in sampled_zone_colors[zone_index].tolist())
                    mapped_led_index = None
                    for led_idx, src_idx in enumerate(device_zone_indices.tolist()):
                        if int(src_idx) == int(zone_index):
                            mapped_led_index = led_idx
                            break
                    if mapped_led_index is None:
                        pre_led_rgb = sampled_rgb
                        final_rgb = sampled_rgb
                    else:
                        pre_led_rgb = tuple(
                            int(c) for c in pre_led_colors[mapped_led_index].tolist()
                        )
                        final_rgb = tuple(
                            int(c) for c in final_zone_colors[mapped_led_index].tolist()
                        )
                    top, right, bottom, left = state.latest_zone_side_counts
                    if zone_index < top:
                        side = "top"
                    elif zone_index < top + right:
                        side = "right"
                    elif zone_index < top + right + bottom:
                        side = "bottom"
                    elif zone_index < top + right + bottom + left:
                        side = "left"
                    else:
                        side = "unknown"
                    zone_diagnostics.append(
                        {
                            "zone_index": zone_index,
                            "side": side,
                            "pixel_rect": rect,
                            "sampled_rgb": sampled_rgb,
                            "output_rgb_before_led_calibration": pre_led_rgb,
                            "final_output_rgb": final_rgb,
                            "mapped_physical_led_index": mapped_led_index,
                            "input_luminance": color_pipeline_diagnostics(
                                input_rgb=sampled_rgb,
                                output_rgb=sampled_rgb,
                                color_style=str(getattr(config, "color_style", "reference")),
                            )["sampled_luminance"],
                            **color_pipeline_diagnostics(
                                input_rgb=sampled_rgb,
                                output_rgb=final_rgb,
                                color_style=str(getattr(config, "color_style", "reference")),
                            ),
                            "led_calibration_applied": pre_led_rgb != final_rgb,
                        }
                    )
                side_var = _side_variance_diagnostics(
                    sampled=sampled_zone_colors,
                    final=final_zone_colors,
                    side_counts=state.latest_zone_side_counts,
                )
                for row in zone_diagnostics:
                    row["side_variance"] = side_var.get(str(row.get("side")), {})
                    row["processing_flattened_side"] = bool(
                        row["side_variance"].get("processing_flattened", False)
                    )
                state.latest_zone_diagnostics = zone_diagnostics
                state.latest_side_variance_diagnostics = side_var
                hid_write_start = time.perf_counter()
                hid_frame_build_ms: float | None = None
                hid_device_write_ms: float | None = None
                hid_flush_or_wait_ms: float | None = None
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
                    timing = send_with_timing(smoothed_colors)
                    hid_frame_build_ms = (
                        float(timing.get("frame_build_ms"))
                        if isinstance(timing, dict) and timing.get("frame_build_ms") is not None
                        else None
                    )
                    hid_device_write_ms = (
                        float(timing.get("device_write_ms"))
                        if isinstance(timing, dict) and timing.get("device_write_ms") is not None
                        else None
                    )
                    hid_flush_or_wait_ms = (
                        float(timing.get("flush_or_wait_ms"))
                        if isinstance(timing, dict) and timing.get("flush_or_wait_ms") is not None
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
                    driver.send_frame(smoothed_colors)
                send_done = time.perf_counter()
                hid_write_ms = (send_done - hid_write_start) * 1000.0
                if hid_device_write_ms is None:
                    hid_device_write_ms = hid_write_ms
                frame_processing_ms = (processing_end - start) * 1000.0
                actual_work_ms = (send_done - start) * 1000.0
                loop_gap_ms = (
                    ((send_done - last_send_done_ts) * 1000.0)
                    if last_send_done_ts is not None
                    else None
                )
                inferred_unattributed_gap_ms = (
                    max(0.0, loop_gap_ms - actual_work_ms) if loop_gap_ms is not None else None
                )
                last_send_done_ts = send_done
                with capture_worker_lock:
                    capture_worker_active_now = bool(capture_worker_active)
                    capture_worker_error_count_now = int(capture_worker_error_count)
                replaced_count = pending_slot.get_replaced_count()
                dropped_delta = max(0, replaced_count - last_replaced_count)
                last_replaced_count = replaced_count
                state.latency_probe.add_stage_sample(
                    FrameTimingSample(
                        stage_ms={
                            STAGE_CAPTURE_WAIT: capture_wait_ms,
                            STAGE_CAPTURE_CALL: capture_call_ms_latest,
                            STAGE_RUNTIME_CAPTURE_CALL: capture_call_ms_latest,
                            STAGE_CAPTURE_WORKER_LOOP_GAP: capture_worker_loop_gap_ms_latest,
                            STAGE_CAPTURE_SUCCESS_INTERVAL: capture_success_interval_ms_latest,
                            STAGE_FRAME_HANDOFF_WAIT: frame_handoff_wait_ms,
                            STAGE_FRAME_AVAILABLE_WAIT: frame_handoff_wait_ms,
                            STAGE_PENDING_FRAME_AGE: pending_frame_age_ms,
                            STAGE_PACING_WAIT: pacing_wait_ms,
                            STAGE_IDLE_WAIT: idle_wait_ms,
                            STAGE_RUNTIME_IDLE_WAIT: idle_wait_ms,
                            STAGE_FRAME_PROCESSING: frame_processing_ms,
                            STAGE_FRAME_CONVERT: processing_timings.frame_convert_ms,  # type: ignore[union-attr]
                            STAGE_ZONE_SAMPLING: processing_timings.zone_sampling_ms,  # type: ignore[union-attr]
                            STAGE_COLOUR_PROCESSING: processing_timings.colour_processing_ms,  # type: ignore[union-attr]
                            STAGE_SMOOTHING: processing_timings.smoothing_ms,  # type: ignore[union-attr]
                            STAGE_LED_CALIBRATION: processing_timings.led_calibration_ms,  # type: ignore[union-attr]
                            STAGE_OUTPUT_PREPARE: processing_timings.output_prepare_ms,  # type: ignore[union-attr]
                            STAGE_ACTUAL_WORK: actual_work_ms,
                            STAGE_HID_WRITE: hid_write_ms,
                            STAGE_HID_FRAME_BUILD: hid_frame_build_ms,
                            STAGE_HID_DEVICE_WRITE: hid_device_write_ms,
                            STAGE_HID_FLUSH_OR_WAIT: hid_flush_or_wait_ms,
                            STAGE_LOOP_GAP: loop_gap_ms,
                            STAGE_INFERRED_UNATTRIBUTED_GAP: inferred_unattributed_gap_ms,
                            "end_to_end_live_ms": None,
                        },
                        target_fps=float(governor.target_fps),
                        fps_cap=float(governor.target_fps),
                        fps_cap_reason="FPS governor dynamic cap",
                        dropped_or_skipped_frames_delta=dropped_delta,
                        counters_delta={
                            "no_pending_frame_ticks": no_pending_frame_ticks,
                            "capture_errors_retries": max(
                                0,
                                capture_worker_error_count_now
                                - last_reported_capture_worker_error_count,
                            ),
                            "capture_worker_error_count": max(
                                0,
                                capture_worker_error_count_now
                                - last_reported_capture_worker_error_count,
                            ),
                        },
                        flags={"capture_worker_active": capture_worker_active_now},
                        labels={
                            "latest_capture_backend_name": latest_capture_backend_name,
                            "capture_backend_method": latest_capture_backend_method,
                            "no_pending_frame_rate_per_second": _no_pending_frame_rate_per_second(
                                no_pending_frame_events, no_pending_started_at
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
                last_reported_capture_worker_error_count = capture_worker_error_count_now
                no_pending_frame_ticks = 0
                capture_to_send_ms = (send_done - captured_at) * 1000.0
                ewma_capture_to_send_ms = (
                    (0.9 * ewma_capture_to_send_ms) + (0.1 * capture_to_send_ms)
                    if ewma_capture_to_send_ms > 0.0
                    else capture_to_send_ms
                )

                state.record_success()
                sent_any_frame = True
                state.first_frame_sent = True
                state.startup_elapsed_ms = max(
                    0.0, (time.perf_counter() - startup_started_at) * 1000.0
                )
                if not state.startup_complete.is_set():
                    state.start_failure_reason = ""
                    state.lifecycle_state = "running"
                    state.mark_startup(True)
                last_sent_zone_count = len(smoothed_colors)
                sent_in_window += 1

                # ---- adaptive FPS governor ------------------------------------
                previous_target = governor.target_fps
                governor.record_frame(actual_work_ms)
                state.target_fps = governor.target_fps
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
        except Exception as e:
            state.record_error(e)
            logger.warning("frame processing failed seq=%s", frame_seq, exc_info=config.verbose)
            if config.verbose:
                print(f"[service] frame error #{state.consecutive_errors} seq={frame_seq}: {e}")

            backoff_s = max(0.0, float(getattr(config, "reinit_backoff_ms", 500)) / 1000.0)
            now_ts = time.perf_counter()
            if should_reinitialize(
                state=state,
                error_limit=error_limit,
                backoff_s=backoff_s,
                now_ts=now_ts,
            ):
                reinitialize_backends(
                    install_drivers=install_drivers,
                    close_backends=close_backends,
                    state=state,
                )

        if (not sent_any_frame) and (not state.startup_complete.is_set()):
            startup_elapsed = time.perf_counter() - startup_started_at
            state.startup_elapsed_ms = max(0.0, startup_elapsed * 1000.0)
            if startup_elapsed >= startup_frame_timeout_s:
                backend_name = latest_capture_backend_name or "unavailable"
                backend_method = latest_capture_backend_method or "unavailable"
                reason = (
                    "Start failed before first frame: capture backend produced no frame "
                    f"within {startup_frame_timeout_s:.1f}s "
                    f"(backend={backend_name}, method={backend_method})."
                )
                state.last_error = reason
                state.last_error_kind = "capture-timeout"
                state.last_error_guidance = "Check capture backend readiness and retry."
                state.start_failure_reason = reason
                state.lifecycle_state = "failed"
                state.mark_startup(False)
                break

        # ---- adaptive pacing (governor-driven) -------------------------
        budget_ms = 1000.0 / max(1, governor.target_fps)
        pacing_wait_s = max(0.0, budget_ms / 1000.0 - (time.perf_counter() - send_done))
        if pacing_wait_s > 0.0:
            last_pacing_wait_ms = pacing_wait_s * 1000.0
            time.sleep(pacing_wait_s)
        else:
            last_pacing_wait_ms = None
        next_deadline = time.perf_counter() + budget_ms / 1000.0

        now = time.perf_counter()
        if now - last_log > log_interval_s:
            window_s = max(0.001, now - last_log)
            send_fps = sent_in_window / window_s
            replaced_frames = pending_slot.get_replaced_count()
            last_log = now
            sent_in_window = 0
            elapsed_ms = (processing_end - start) * 1000.0
            logger.info(
                "service_tick seq=%s fps=%s elapsed_ms=%.2f zones=%s errors=%s "
                "send_fps=%.1f capture_to_send_ms=%.2f replaced_frames=%s",
                frame_seq,
                governor.target_fps,
                elapsed_ms,
                last_sent_zone_count,
                state.consecutive_errors,
                send_fps,
                ewma_capture_to_send_ms,
                replaced_frames,
            )
            if config.verbose:
                print(
                    f"[service] tick fps={governor.target_fps} elapsed_ms={elapsed_ms:.2f} "
                    f"zones={last_sent_zone_count} send_fps={send_fps:.1f} "
                    f"capture_to_send_ms={ewma_capture_to_send_ms:.2f} "
                    f"replaced_frames={replaced_frames}"
                )

    if capture_thread.is_alive():
        capture_thread.join(timeout=2.0)
        if capture_thread.is_alive():
            logger.warning(
                "capture worker thread did not exit within shutdown timeout; "
                "it may still be blocked in capture backend IO"
            )


def _run_loop_pipeline(
    *,
    config: AppConfig,
    state: RuntimeState,
    get_capture,
    get_driver,
    install_drivers,
    close_backends,
) -> None:
    _gamut_init_from_config(config)
    fps = max(1, int(config.fps))
    governor = FPSGovernor(initial_fps=fps)
    state.target_fps = governor.target_fps
    gov_lock = threading.Lock()
    1.0 / fps
    log_interval_s = float(getattr(config, "status_log_interval_s", 5.0))
    error_limit = max(1, int(getattr(config, "max_consecutive_errors", 5)))
    startup_frame_timeout_s = max(0.1, float(getattr(config, "startup_frame_timeout_s", 5.0)))
    startup_started_at = time.perf_counter()

    # Capacity 2 per buffer: latest-frame semantics with minimal stale buffering.
    capture_buf: SPSCRingBuffer[CapturePayload] = SPSCRingBuffer(capacity=2)
    process_buf: SPSCRingBuffer[ProcessedPayload] = SPSCRingBuffer(capacity=2)

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
    frame_seq: int = 0

    # ---- capture worker -------------------------------------------------
    def _capture_worker() -> None:
        nonlocal capture_worker_active, capture_call_ms_latest
        nonlocal capture_worker_loop_gap_ms_latest, capture_success_interval_ms_latest
        nonlocal last_capture_completed_ts, last_capture_success_ts
        nonlocal latest_capture_backend_name, latest_capture_backend_method
        nonlocal capture_worker_error_count, capture_worker_failures
        nonlocal no_pending_frame_events
        nonlocal process_worker_error_count

        with metrics_lock:
            capture_worker_active = True
        while not state.stop_event.is_set():
            state.reinit_pause.wait(timeout=0.001)
            try:
                if state.is_reinitializing:
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
                use_drm_rects = bool(getattr(config, "drm_zone_patch_capture", False)) and bool(
                    zone_rects
                )
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
                if not capture_buf.try_push(
                    CapturePayload(
                        captured_at=capture_end,
                        frame=frame,
                        precomputed_zone_colors=precomputed,
                    )
                ):
                    logger.debug("capture worker: ring buffer full; dropping frame")
                    with metrics_lock:
                        no_pending_frame_events += 1
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
                logger.debug("capture worker error: %s", exc)
                time.sleep(0.005)
        with metrics_lock:
            capture_worker_active = False

    # ---- process worker -------------------------------------------------
    process_worker_error: Exception | None = None

    def _process_worker() -> None:
        nonlocal process_worker_error, process_worker_error_count, frame_seq
        while not state.stop_event.is_set():
            state.reinit_pause.wait(timeout=0.001)
            try:
                if state.is_reinitializing:
                    time.sleep(0.001)
                    continue
                payload = capture_buf.pop_latest(timeout=0.01)
                if payload is None:
                    continue

                frame = payload.frame
                precomputed_zone_colors = payload.precomputed_zone_colors
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
                    # Log warning periodically (every ~1s at 60fps) instead of just once
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
                    state.consecutive_black_frames = 0

                driver = get_driver()
                if driver is None:
                    continue

                zones_px, device_zone_indices = _ensure_runtime_artifacts(
                    state=state,
                    config=config,
                    img_w=img_w,
                    img_h=img_h,
                    detected_device_zone_count=getattr(
                        driver,
                        "reported_zone_count",
                        getattr(driver, "zone_count", None),
                    ),
                )

                if (
                    state.calibration_status == CALIBRATION_INCOMPLETE_STATUS
                    or len(device_zone_indices) <= 0
                ):
                    message = state.calibration_status_message or CALIBRATION_INCOMPLETE_MESSAGE
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
                    frame_seq += 1
                cap_backend = get_capture()
                if cap_backend is not None:
                    hdr_diag = getattr(cap_backend, "last_hdr_diagnostics", None) or {}
                    if isinstance(hdr_diag, dict):
                        state.skip_display_gamut_adaptation = bool(
                            hdr_diag.get("skip_display_gamut_adaptation", False)
                        )
                pipeline_params = build_pipeline_params_from_config(
                    config,
                    return_diagnostics=True,
                    build_zone_diagnostics=build_diagnostics,
                    skip_display_gamut_adaptation=state.skip_display_gamut_adaptation,
                )
                light_spread = pipeline_params.light_spread
                if state.flattening_mitigation_active:
                    light_spread = "off"
                processed = process_frame(
                    frame=frame,
                    precomputed_zone_colors=precomputed_zone_colors,
                    prev_smoothed_colors=state.prev_smoothed_colors,
                    zones_px=zones_px,
                    device_zone_indices=device_zone_indices,  # type: ignore[arg-type]
                    compositor_hdr_mode=pipeline_params.compositor_hdr_mode,
                    sdr_boost_nits=pipeline_params.sdr_boost_nits,
                    hdr_max_nits=pipeline_params.hdr_max_nits,
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
                    return_diagnostics=True,
                    build_zone_diagnostics=build_diagnostics,
                )
                (
                    smoothed_colors,
                    sampled_zone_colors,
                    pre_led_colors,
                    final_zone_colors,
                    processing_timings,
                ) = processed

                state.prev_smoothed_colors = smoothed_colors  # type: ignore[assignment]
                state.first_frame_processed = True
                state.last_frame_width = int(img_w)
                state.last_frame_height = int(img_h)
                if frame is not None:
                    state.latest_frame_rgb = frame
                state.latest_zones_px = list(zones_px)

                zone_diagnostics: list[dict[str, object]] = []
                if build_diagnostics:
                    for zone_index, rect in enumerate(zones_px):
                        sampled_rgb = tuple(
                            int(c)
                            for c in sampled_zone_colors[zone_index].tolist()  # type: ignore[union-attr]
                        )
                        mapped_led_index = None
                        for led_idx, src_idx in enumerate(device_zone_indices.tolist()):
                            if int(src_idx) == int(zone_index):
                                mapped_led_index = led_idx
                                break
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
                        top, right, bottom, left = state.latest_zone_side_counts
                        if zone_index < top:
                            side = "top"
                        elif zone_index < top + right:
                            side = "right"
                        elif zone_index < top + right + bottom:
                            side = "bottom"
                        elif zone_index < top + right + bottom + left:
                            side = "left"
                        else:
                            side = "unknown"
                        zone_diagnostics.append(
                            {
                                "zone_index": zone_index,
                                "side": side,
                                "pixel_rect": rect,
                                "sampled_rgb": sampled_rgb,
                                "output_rgb_before_led_calibration": pre_led_rgb,
                                "final_output_rgb": final_rgb,
                                "mapped_physical_led_index": mapped_led_index,
                                "input_luminance": color_pipeline_diagnostics(
                                    input_rgb=sampled_rgb,
                                    output_rgb=sampled_rgb,
                                    color_style=str(getattr(config, "color_style", "reference")),
                                )["sampled_luminance"],
                                **color_pipeline_diagnostics(
                                    input_rgb=sampled_rgb,
                                    output_rgb=final_rgb,
                                    color_style=str(getattr(config, "color_style", "reference")),
                                ),
                                "led_calibration_applied": pre_led_rgb != final_rgb,
                            }
                        )
                    side_var = _side_variance_diagnostics(
                        sampled=sampled_zone_colors,  # type: ignore[arg-type]
                        final=final_zone_colors,  # type: ignore[arg-type]
                        side_counts=state.latest_zone_side_counts,
                    )
                    for row in zone_diagnostics:
                        row["side_variance"] = side_var.get(str(row.get("side")), {})  # type: ignore[attr-defined]
                        row["processing_flattened_side"] = bool(
                            row["side_variance"].get("processing_flattened", False)  # type: ignore[attr-defined]
                        )
                    state.latest_zone_diagnostics = zone_diagnostics
                    state.latest_side_variance_diagnostics = side_var
                    state.flattening_mitigation_active = any(
                        bool(side.get("processing_flattened", False)) for side in side_var.values()
                    )
                else:
                    side_var = {}
                    state.flattening_mitigation_active = False

                pushed = process_buf.push(
                    ProcessedPayload(
                        smoothed_colors=smoothed_colors,  # type: ignore[arg-type]
                        captured_at=captured_at,
                        zones_px=list(zones_px),
                        device_zone_indices=device_zone_indices,
                        sampled_zone_colors=sampled_zone_colors,  # type: ignore[arg-type]
                        pre_led_colors=pre_led_colors,  # type: ignore[arg-type]
                        final_zone_colors=final_zone_colors,  # type: ignore[arg-type]
                        processing_timings=processing_timings,
                        zone_diagnostics=zone_diagnostics,
                        side_var=side_var,
                    ),
                    timeout=0.01,
                )
                if not pushed:
                    logger.warning(
                        "process worker: process_buf push timed out; dropping frame "
                        "(HID writer may be stalled)"
                    )
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
        sent_in_window = 0
        last_log = time.perf_counter()
        last_send_done_ts: float | None = None

        while not state.stop_event.is_set():
            state.reinit_pause.wait(timeout=0.001)
            try:
                if state.is_reinitializing:
                    time.sleep(0.001)
                    continue
                payload = process_buf.pop_latest(timeout=0.01)
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
                                STAGE_FRAME_AVAILABLE_WAIT: 10.0,
                                STAGE_IDLE_WAIT: 10.0,  # poll interval
                                STAGE_RUNTIME_IDLE_WAIT: 10.0,
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

                # HID write
                hid_write_start = time.perf_counter()
                hid_frame_build_ms: float | None = None
                hid_device_write_ms: float | None = None
                hid_flush_or_wait_ms: float | None = None
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
                inferred_unattributed_gap_ms = (
                    max(0.0, loop_gap_ms - actual_work_ms) if loop_gap_ms is not None else None
                )
                last_send_done_ts = send_done

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
                dropped_delta = capture_buf.dropped_count()
                capture_buf.reset_dropped()

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
                            STAGE_LOOP_GAP: loop_gap_ms,
                            STAGE_INFERRED_UNATTRIBUTED_GAP: inferred_unattributed_gap_ms,
                            "end_to_end_live_ms": None,
                        },
                        target_fps=float(governor.target_fps),
                        fps_cap=float(governor.target_fps),
                        fps_cap_reason="FPS governor dynamic cap",
                        dropped_or_skipped_frames_delta=dropped_delta,
                        counters_delta={
                            "capture_worker_error_count": max(0, cap_error_now),
                        },
                        flags={"capture_worker_active": cap_active},
                        labels={
                            "latest_capture_backend_name": latest_capture_backend_name,
                            "capture_backend_method": latest_capture_backend_method,
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
                budget_ms = 1000.0 / max(1, governor.target_fps)
                pacing_wait_s = max(0.0, budget_ms / 1000.0 - actual_work_ms)
                if pacing_wait_s > 0.0:
                    time.sleep(pacing_wait_s)

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
                reason = (
                    "Start failed before first frame: capture backend "
                    f"produced no frame within {startup_frame_timeout_s:.1f}s "
                    f"(backend={backend}, method={method})."
                )
                state.last_error = reason
                state.last_error_kind = "capture-timeout"
                state.last_error_guidance = "Check capture backend readiness and retry."
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
                    with metrics_lock:
                        capture_worker_failures = 0
                        capture_worker_error_count = 0
                        process_worker_error_count = 0
                    state.consecutive_errors = 0

    # ---- shutdown -------------------------------------------------------
    for t in threads:
        t.join(timeout=3.0)
        if t.is_alive():
            logger.warning(
                "%s thread did not exit within shutdown timeout (3s); "
                "it may still be blocked in IO",
                t.name,
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
) -> None:
    """Entry point for the mirroring runtime loop.

    Dispatches to either the legacy single-threaded path or the 3-stage
    pipeline (default) based on *use_legacy_pipeline*.
    """
    if use_legacy_pipeline:
        _run_loop_legacy(
            config=config,
            state=state,
            get_capture=get_capture,
            get_driver=get_driver,
            install_drivers=install_drivers,
            close_backends=close_backends,
        )
    else:
        _run_loop_pipeline(
            config=config,
            state=state,
            get_capture=get_capture,
            get_driver=get_driver,
            install_drivers=install_drivers,
            close_backends=close_backends,
        )
