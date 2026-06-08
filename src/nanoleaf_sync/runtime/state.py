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

    def _assert_locked(self) -> None:
        if not self._lock.locked():
            raise RuntimeError("RuntimeState multi-field update requires _lock")

    def reset_for_start(self) -> None:
        self.reinit_pause.clear()
        self.prev_smoothed_colors = []
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

    def mark_calibration_incomplete(self, message: str) -> None:
        self.calibration_status = CALIBRATION_INCOMPLETE_STATUS
        self.calibration_status_message = str(message or "calibration_incomplete")
        self.last_error = self.calibration_status_message
        self.last_error_kind = CALIBRATION_INCOMPLETE_STATUS
        self.last_error_guidance = "Open Settings > Corner calibration and assign all four corners, then start mirroring again."
        self.start_failure_reason = self.calibration_status_message
        self.lifecycle_state = CALIBRATION_INCOMPLETE_STATUS

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
