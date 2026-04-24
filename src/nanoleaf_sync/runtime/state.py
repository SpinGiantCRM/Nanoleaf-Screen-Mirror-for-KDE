from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

import numpy as np

from nanoleaf_sync.capture.latency_probe import LatencyProbe

RGBTuple = Tuple[int, int, int]
ZoneRect = Tuple[int, int, int, int]
DeviceZoneMappingSignature = Tuple[
    int,
    int,
    int,
    int,
    bool,
    bool,
    Tuple[int, ...],
    bool,
    Tuple[int, ...],
    str,
    int,
    int,
    int,
    int,
    Tuple[int, ...],
]


@dataclass
class RuntimeState:
    stop_event: threading.Event = field(default_factory=threading.Event)
    startup_complete: threading.Event = field(default_factory=threading.Event)
    startup_succeeded: bool = False

    prev_smoothed_colors: List[RGBTuple] = field(default_factory=list)

    cached_zone_rects: Optional[List[ZoneRect]] = None
    zone_rects_signature: Optional[Tuple[int, int, Tuple[Tuple[float, float, float, float], ...]]] = None

    cached_device_zone_indices: Optional[List[int]] = None
    cached_device_zone_indices_np: Optional[np.ndarray] = None
    device_zone_mapping_signature: Optional[DeviceZoneMappingSignature] = None

    consecutive_errors: int = 0
    last_error: Optional[str] = None
    last_error_kind: Optional[str] = None
    last_error_guidance: Optional[str] = None
    frames_sent: int = 0
    last_frame_timestamp: Optional[float] = None
    latency_probe: LatencyProbe = field(default_factory=LatencyProbe)
    last_reinit_ts: float = 0.0
    is_reinitializing: bool = False

    def reset_for_start(self) -> None:
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
        self.is_reinitializing = False

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
        capture_backend_name: Optional[str],
        capture_path: Optional[str],
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
            "consecutive_errors": self.consecutive_errors,
            "frames_sent": self.frames_sent,
            "last_frame_timestamp": self.last_frame_timestamp,
            "latency_measurement": (
                None
                if measurement is None
                else {
                    "sample_count": measurement.sample_count,
                    "capture_interval_median_ms": measurement.capture_interval_median_ms,
                    "capture_interval_p95_ms": measurement.capture_interval_p95_ms,
                    "pipeline_median_ms": measurement.pipeline_median_ms,
                    "pipeline_p95_ms": measurement.pipeline_p95_ms,
                    "pipeline_jitter_ms": measurement.pipeline_jitter_ms,
                }
            ),
            "max_consecutive_errors": max_consecutive_errors,
            "reinit_backoff_ms": reinit_backoff_ms,
        }


def classify_capture_mode(
    *,
    capture_backend_name: Optional[str],
    capture_path: Optional[str],
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
