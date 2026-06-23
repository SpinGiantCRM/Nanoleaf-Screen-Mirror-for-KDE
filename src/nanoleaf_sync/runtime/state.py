from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from nanoleaf_sync.capture.latency_probe import LatencyProbe
from nanoleaf_sync.color._types import RGBTuple
from nanoleaf_sync.runtime.calibration_resolver import (
    CALIBRATION_INCOMPLETE_STATUS,
    CALIBRATION_READY_STATUS,
    DEVICE_ZONE_MISMATCH_STATUS,
)

ZoneRect = tuple[int, int, int, int]
DeviceZoneMappingSignature = tuple[Any, ...]


@dataclass
class RuntimeState:
    # Individual field reads/writes are GIL-safe; multi-field updates should
    # acquire _lock for a consistent snapshot.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    stop_event: threading.Event = field(default_factory=threading.Event)
    startup_complete: threading.Event = field(default_factory=threading.Event)
    reinit_pause: threading.Event = field(default_factory=threading.Event)
    startup_succeeded: bool = False

    prev_smoothed_colors: list[RGBTuple] = field(default_factory=list)
    prev_smooth_float_colors: list[RGBTuple] = field(default_factory=list)
    prev_sent_colors: list[RGBTuple] = field(default_factory=list)
    prev_sampled_zone_colors: list[RGBTuple] = field(default_factory=list)
    prev_palette_algorithms: list[str] = field(default_factory=list)
    zone_palette_temporal_states: list[dict[str, object]] = field(default_factory=list)
    palette_frame_index: int = 0
    prior_zone_sample_motion: float = 0.0
    prior_area_average_mode: bool = False

    cached_zone_rects: list[ZoneRect] | None = None
    zone_rects_signature: tuple[int, int, tuple[tuple[float, float, float, float], ...]] | None = (
        None
    )

    cached_device_zone_indices: list[int] | None = None
    cached_device_zone_indices_np: np.ndarray | None = None
    device_zone_mapping_signature: DeviceZoneMappingSignature | None = None

    consecutive_errors: int = 0
    last_error: str | None = None
    last_error_kind: str | None = None
    last_error_guidance: str | None = None
    frames_sent: int = 0
    last_frame_timestamp: float | None = None
    latency_probe: LatencyProbe = field(default_factory=LatencyProbe)
    last_reinit_ts: float = 0.0
    is_reinitializing: bool = False
    last_frame_width: int = 0
    last_frame_height: int = 0
    latest_frame_rgb: np.ndarray | None = None
    latest_zones_px: list[ZoneRect] = field(default_factory=list)
    latest_zone_side_counts: tuple[int, int, int, int] = (0, 0, 0, 0)
    latest_edge_sampling_thickness: float | None = None
    latest_zone_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    latest_side_variance_diagnostics: dict[str, dict[str, float | bool]] = field(
        default_factory=dict
    )
    configured_priority_mode: str = "normal"
    effective_nice_value: int | None = None
    priority_apply_status: str = "not_attempted"
    priority_apply_error: str = ""
    lifecycle_state: str = "idle"
    start_failure_reason: str = ""
    capture_backend_ready: bool = False
    driver_ready: bool = False
    first_frame_seen: bool = False
    first_frame_processed: bool = False
    first_frame_sent: bool = False
    startup_elapsed_ms: float = 0.0
    calibration_status: str = CALIBRATION_READY_STATUS
    calibration_status_message: str = ""
    target_fps: int = 60
    consecutive_black_frames: int = 0
    total_black_frames: int = 0
    latest_frame_mean_brightness: float = 0.0
    latest_zone_centers: list[tuple[int, int]] = field(default_factory=list)
    latest_zone_rects_display: list[tuple[int, int, int, int]] = field(default_factory=list)
    flattening_mitigation_active: bool = False
    skip_display_gamut_adaptation: bool = False
    sdr_boost_compensation_enabled: bool = True
    latest_staleness_ms: float = 0.0
    output_healthy: bool = False
    governor_p95_latency_ms: float = 0.0
    predictive_sync_active: bool = False
    predictive_lookahead_frames: float = 0.0
    predictive_scene_cut_suppressed: bool = False
    stale_output_dropped_frames: int = 0
    duplicate_output_skipped_frames: int = 0
    output_owner_dropped_frames: int = 0
    last_stale_frame_age_ms: float = 0.0
    max_send_age_ms: float = 0.0
    stale_drop_reason: str = ""
    stale_drop_window_started_at: float = 0.0
    stale_drop_window_events: int = 0
    device_zone_count_source: str = ""
    configured_device_zone_count: int = 0
    detected_device_zone_count: int | None = None
    effective_device_zone_count: int = 0
    device_zone_count_mismatch: bool = False
    mapping_repair_required: bool = False
    device_zone_override_active: bool = False
    latest_frame_context: object | None = None
    latest_color_context: object | None = None
    latest_capture_source_identity: dict[str, object] | None = None
    capture_source_change_count: int = 0
    metadata_hysteresis_transitions: int = 0
    sampling_mode_dwell_remaining: int = 0
    smoothing_dimension_signature: tuple[int, int] | None = None
    dark_zone_stabilize_hold: list[bool] = field(default_factory=list)
    portal_selection_started_at: float | None = None

    def _assert_locked(self) -> None:
        if not self._lock.locked():
            raise RuntimeError("RuntimeState multi-field update requires _lock")

    def reset_for_start(self) -> None:
        self.reinit_pause.clear()
        self.prev_smoothed_colors = []
        self.prev_smooth_float_colors = []
        self.prev_sent_colors = []
        self.prev_sampled_zone_colors = []
        self.prev_palette_algorithms = []
        self.zone_palette_temporal_states = []
        self.palette_frame_index = 0
        self.prior_zone_sample_motion = 0.0
        self.prior_area_average_mode = False
        self.cached_zone_rects = None
        self.zone_rects_signature = None
        self.cached_device_zone_indices = None
        self.cached_device_zone_indices_np = None
        self.device_zone_mapping_signature = None
        self.consecutive_errors = 0
        self.last_error = None
        self.last_error_kind = None
        self.last_error_guidance = None
        self.frames_sent = 0
        self.last_frame_timestamp = None
        self.latency_probe = LatencyProbe()
        self.last_reinit_ts = 0.0
        self.is_reinitializing = False
        self.last_frame_width = 0
        self.last_frame_height = 0
        self.latest_frame_rgb = None
        self.latest_zones_px = []
        self.latest_zone_side_counts = (0, 0, 0, 0)
        self.latest_edge_sampling_thickness = None
        self.latest_zone_diagnostics = []
        self.latest_side_variance_diagnostics = {}
        self.configured_priority_mode = "normal"
        self.effective_nice_value = None
        self.priority_apply_status = "not_attempted"
        self.priority_apply_error = ""
        self.lifecycle_state = "starting"
        self.start_failure_reason = ""
        self.capture_backend_ready = False
        self.driver_ready = False
        self.first_frame_seen = False
        self.first_frame_processed = False
        self.first_frame_sent = False
        self.startup_elapsed_ms = 0.0
        self.calibration_status = CALIBRATION_READY_STATUS
        self.calibration_status_message = ""
        self.target_fps = 60
        self.consecutive_black_frames = 0
        self.total_black_frames = 0
        self.latest_frame_mean_brightness = 0.0
        self.sdr_boost_compensation_enabled = True
        self.latest_staleness_ms = 0.0
        self.output_healthy = False
        self.governor_p95_latency_ms = 0.0
        self.predictive_sync_active = False
        self.predictive_lookahead_frames = 0.0
        self.predictive_scene_cut_suppressed = False
        self.stale_output_dropped_frames = 0
        self.duplicate_output_skipped_frames = 0
        self.output_owner_dropped_frames = 0
        self.last_stale_frame_age_ms = 0.0
        self.max_send_age_ms = 0.0
        self.stale_drop_reason = ""
        self.stale_drop_window_started_at = 0.0
        self.stale_drop_window_events = 0
        self.device_zone_count_source = ""
        self.configured_device_zone_count = 0
        self.detected_device_zone_count = None
        self.effective_device_zone_count = 0
        self.device_zone_count_mismatch = False
        self.mapping_repair_required = False
        self.device_zone_override_active = False
        self.latest_frame_context = None
        self.latest_color_context = None
        self.latest_capture_source_identity = None
        self.capture_source_change_count = 0
        self.metadata_hysteresis_transitions = 0
        self.sampling_mode_dwell_remaining = 0
        self.smoothing_dimension_signature = None
        self.dark_zone_stabilize_hold = []
        self.portal_selection_started_at = None

    def clear_smoothing_history(self) -> None:
        self.prev_smoothed_colors = []
        self.prev_smooth_float_colors = []
        self.prev_sent_colors = []
        self.prev_sampled_zone_colors = []
        self.prev_palette_algorithms = []
        self.zone_palette_temporal_states = []
        self.palette_frame_index = 0
        self.prior_zone_sample_motion = 0.0
        self.prior_area_average_mode = False
        self.sampling_mode_dwell_remaining = 0
        self.dark_zone_stabilize_hold = []

    def mark_calibration_incomplete(self, message: str) -> None:
        self.calibration_status = CALIBRATION_INCOMPLETE_STATUS
        self.calibration_status_message = str(message or "calibration_incomplete")
        self.last_error = self.calibration_status_message
        self.last_error_kind = CALIBRATION_INCOMPLETE_STATUS
        self.last_error_guidance = (
            "Open Settings > Corner calibration and assign all four corners, "
            "then start mirroring again."
        )
        self.start_failure_reason = self.calibration_status_message
        self.lifecycle_state = CALIBRATION_INCOMPLETE_STATUS

    def mark_device_zone_mismatch(self, message: str, *, authority: object | None = None) -> None:
        self.calibration_status = DEVICE_ZONE_MISMATCH_STATUS
        self.calibration_status_message = str(message or DEVICE_ZONE_MISMATCH_STATUS)
        self.last_error = self.calibration_status_message
        self.last_error_kind = DEVICE_ZONE_MISMATCH_STATUS
        self.last_error_guidance = (
            "Open Settings > Corner calibration, confirm the physical strip LED count, "
            "then rerun calibration. If you intentionally use a non-standard profile, "
            "enable allow_zone_count_override in advanced settings."
        )
        self.start_failure_reason = self.calibration_status_message
        self.lifecycle_state = DEVICE_ZONE_MISMATCH_STATUS
        self.mapping_repair_required = True
        self.device_zone_count_mismatch = True
        if authority is not None:
            self.device_zone_count_source = str(
                getattr(authority, "device_zone_count_source", "") or ""
            )
            self.configured_device_zone_count = int(
                getattr(authority, "configured_device_zone_count", 0) or 0
            )
            self.detected_device_zone_count = getattr(authority, "detected_device_zone_count", None)
            self.effective_device_zone_count = int(
                getattr(authority, "effective_device_zone_count", 0) or 0
            )
            self.device_zone_override_active = bool(getattr(authority, "override_active", False))

    def record_stale_output_drop(
        self,
        *,
        frame_age_ms: float,
        max_send_age_ms: float,
        reason: str,
    ) -> None:
        now = time.perf_counter()
        self.stale_output_dropped_frames += 1
        self.last_stale_frame_age_ms = float(frame_age_ms)
        self.max_send_age_ms = float(max_send_age_ms)
        self.stale_drop_reason = str(reason or "")
        if self.stale_drop_window_started_at <= 0.0:
            self.stale_drop_window_started_at = now
        self.stale_drop_window_events += 1

    def stale_drop_rate_per_second(self) -> float:
        started = float(self.stale_drop_window_started_at or 0.0)
        if started <= 0.0:
            return 0.0
        elapsed = max(0.001, time.perf_counter() - started)
        return float(self.stale_drop_window_events) / elapsed

    def mark_startup(self, succeeded: bool) -> None:
        self.startup_succeeded = succeeded
        self.startup_complete.set()

    def record_success(self) -> None:
        self.consecutive_errors = 0
        self.last_error = None
        self.last_error_kind = None
        self.last_error_guidance = None
        self.frames_sent += 1
        self.last_frame_timestamp = time.time()

    def record_error(self, error: Exception) -> int:
        from nanoleaf_sync.runtime.errors import translate_runtime_error

        translated = translate_runtime_error(error)
        self.consecutive_errors += 1
        self.last_error = translated.summary
        self.last_error_kind = translated.kind
        self.last_error_guidance = translated.guidance
        return self.consecutive_errors

    def status_snapshot(
        self,
        *,
        running: bool,
        capture_backend_name: str | None,
        capture_path: str | None,
        capture_width: int,
        capture_height: int,
        max_consecutive_errors: int,
        reinit_backoff_ms: int,
    ) -> dict[str, Any]:
        with self._lock:
            return self._status_snapshot_unlocked(
                running=running,
                capture_backend_name=capture_backend_name,
                capture_path=capture_path,
                capture_width=capture_width,
                capture_height=capture_height,
                max_consecutive_errors=max_consecutive_errors,
                reinit_backoff_ms=reinit_backoff_ms,
            )

    def _status_snapshot_unlocked(
        self,
        *,
        running: bool,
        capture_backend_name: str | None,
        capture_path: str | None,
        capture_width: int,
        capture_height: int,
        max_consecutive_errors: int,
        reinit_backoff_ms: int,
    ) -> dict[str, Any]:
        measurement = self.latency_probe.measurement()
        return {
            "running": running,
            "last_error": self.last_error,
            "capture_backend": capture_backend_name,
            "last_error_kind": self.last_error_kind,
            "last_error_guidance": self.last_error_guidance,
            "capture_path": capture_path,
            "capture_mode": classify_capture_mode(
                capture_backend_name=capture_backend_name,
                capture_path=capture_path,
            ),
            "capture_width": capture_width,
            "capture_height": capture_height,
            "captured_frame_width": int(self.last_frame_width or 0),
            "captured_frame_height": int(self.last_frame_height or 0),
            "consecutive_errors": self.consecutive_errors,
            "frames_sent": self.frames_sent,
            "last_frame_timestamp": self.last_frame_timestamp,
            "latency_measurement": (
                None
                if measurement is None
                else {
                    "live_mirroring_only": bool(measurement.live_mirroring_only),
                    "dropped_or_skipped_frames": int(measurement.dropped_or_skipped_frames),
                    "target_fps": float(measurement.target_fps),
                    "fps_cap": float(measurement.fps_cap),
                    "fps_cap_reason": str(measurement.fps_cap_reason),
                    "effective_output_fps": float(measurement.effective_output_fps),
                    "counters": {
                        str(key): int(value) for key, value in measurement.counters.items()
                    },
                    "flags": {str(key): bool(value) for key, value in measurement.flags.items()},
                    "labels": {str(key): str(value) for key, value in measurement.labels.items()},
                    "stages": {
                        stage: {
                            "available": bool(stats.available),
                            "sample_count": int(stats.sample_count),
                            "median_ms": float(stats.median_ms),
                            "p95_ms": float(stats.p95_ms),
                            "max_ms": float(stats.max_ms),
                        }
                        for stage, stats in measurement.stages.items()
                    },
                }
            ),
            "max_consecutive_errors": max_consecutive_errors,
            "reinit_backoff_ms": reinit_backoff_ms,
            "configured_priority_mode": str(self.configured_priority_mode or "normal"),
            "effective_nice_value": self.effective_nice_value,
            "priority_apply_status": str(self.priority_apply_status or "not_attempted"),
            "priority_apply_error": str(self.priority_apply_error or ""),
            "lifecycle_state": str(self.lifecycle_state or "idle"),
            "start_failure_reason": str(self.start_failure_reason or ""),
            "capture_backend_ready": bool(self.capture_backend_ready),
            "driver_ready": bool(self.driver_ready),
            "first_frame_seen": bool(self.first_frame_seen),
            "first_frame_processed": bool(self.first_frame_processed),
            "first_frame_sent": bool(self.first_frame_sent),
            "startup_elapsed_ms": float(self.startup_elapsed_ms or 0.0),
            "calibration_status": str(self.calibration_status or CALIBRATION_READY_STATUS),
            "calibration_status_message": str(self.calibration_status_message or ""),
            "consecutive_black_frames": self.consecutive_black_frames,
            "total_black_frames": self.total_black_frames,
            "latest_frame_mean_brightness": self.latest_frame_mean_brightness,
            "governor_p95_latency_ms": float(self.governor_p95_latency_ms),
            "latest_staleness_ms": float(self.latest_staleness_ms),
            "predictive_sync_active": bool(self.predictive_sync_active),
            "predictive_lookahead_frames": float(self.predictive_lookahead_frames),
            "predictive_scene_cut_suppressed": bool(self.predictive_scene_cut_suppressed),
            "sdr_boost_compensation_enabled": bool(self.sdr_boost_compensation_enabled),
            "skip_display_gamut_adaptation": bool(self.skip_display_gamut_adaptation),
            "stale_output_dropped_frames": int(self.stale_output_dropped_frames),
            "duplicate_output_skipped_frames": int(self.duplicate_output_skipped_frames),
            "output_owner_dropped_frames": int(self.output_owner_dropped_frames),
            "last_stale_frame_age_ms": float(self.last_stale_frame_age_ms),
            "max_send_age_ms": float(self.max_send_age_ms),
            "stale_drop_reason": str(self.stale_drop_reason or ""),
            "stale_drop_rate_per_second": float(self.stale_drop_rate_per_second()),
            "device_zone_count_source": str(self.device_zone_count_source or ""),
            "configured_device_zone_count": int(self.configured_device_zone_count),
            "detected_device_zone_count": self.detected_device_zone_count,
            "effective_device_zone_count": int(self.effective_device_zone_count),
            "device_zone_count_mismatch": bool(self.device_zone_count_mismatch),
            "mapping_repair_required": bool(self.mapping_repair_required),
            "device_zone_override_active": bool(self.device_zone_override_active),
            "latest_frame_context": (
                self.latest_frame_context.as_dict()
                if self.latest_frame_context is not None
                and hasattr(self.latest_frame_context, "as_dict")
                else None
            ),
            "latest_color_context": (
                self.latest_color_context.as_dict()
                if self.latest_color_context is not None
                and hasattr(self.latest_color_context, "as_dict")
                else None
            ),
            "latest_capture_source_identity": self.latest_capture_source_identity,
            "capture_source_change_count": int(self.capture_source_change_count),
            "metadata_hysteresis_transitions": int(self.metadata_hysteresis_transitions),
            "sampling_mode_dwell_remaining": int(self.sampling_mode_dwell_remaining),
        }


def classify_capture_mode(
    *,
    capture_backend_name: str | None,
    capture_path: str | None,
) -> str:
    if capture_backend_name == "mock":
        return "mock"
    if capture_backend_name == "kwin-dbus":
        return "kwin-dbus"
    if capture_backend_name == "xdg-portal":
        return "xdg-portal"
    if capture_backend_name == "kmsgrab" and capture_path == "kwin-dbus":
        return "kwin-fallback"
    if capture_backend_name == "replay":
        return "replay"
    if capture_backend_name == "kmsgrab":
        return "real"
    return "unknown"
