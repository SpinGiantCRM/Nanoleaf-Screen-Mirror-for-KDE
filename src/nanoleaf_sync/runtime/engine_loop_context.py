"""Shared mutable context for the mirroring runtime loop workers."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from nanoleaf_sync.capture.interfaces import CaptureBackend
from nanoleaf_sync.capture.source_identity import SourceIdentityTracker
from nanoleaf_sync.color.metadata_hysteresis import MetadataHysteresisTracker
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.device.interfaces import DeviceDriver
from nanoleaf_sync.runtime.fps_governor import FPSGovernor
from nanoleaf_sync.runtime.ring_buf import CapturePayload, ProcessedPayload, SPSCRingBuffer
from nanoleaf_sync.runtime.state import RuntimeState


@dataclass
class LoopPipelineContext:
    config: AppConfig
    state: RuntimeState
    get_capture: Callable[[], CaptureBackend | None]
    get_driver: Callable[[], DeviceDriver | None]
    install_drivers: Callable[[], bool]
    close_backends: Callable[[], None]
    can_mirroring_write: Callable[[], bool] | None

    governor: FPSGovernor
    gov_lock: threading.Lock = field(default_factory=threading.Lock)
    log_interval_s: float = 5.0
    error_limit: int = 5
    startup_frame_timeout_s: float = 5.0
    startup_started_at: float = field(default_factory=time.perf_counter)

    capture_buf: SPSCRingBuffer[CapturePayload] = field(
        default_factory=lambda: SPSCRingBuffer(capacity=4)
    )
    process_buf: SPSCRingBuffer[ProcessedPayload] = field(
        default_factory=lambda: SPSCRingBuffer(capacity=8)
    )

    metrics_lock: threading.Lock = field(default_factory=threading.Lock)
    latest_capture_backend_name: str = "unavailable"
    latest_capture_backend_method: str = ""
    capture_call_ms_latest: float | None = None
    capture_worker_loop_gap_ms_latest: float | None = None
    capture_success_interval_ms_latest: float | None = None
    last_capture_completed_ts: float | None = None
    last_capture_success_ts: float | None = None
    capture_worker_active: bool = False
    capture_worker_error_count: int = 0
    capture_worker_failures: int = 0
    process_worker_error_count: int = 0
    no_pending_frame_events: int = 0
    no_pending_started_at: float = field(default_factory=time.perf_counter)
    last_sent_zone_count: int = 0
    ewma_capture_to_send_ms: float = 0.0
    hid_loop_gap_ewma_ms: float | None = None
    hid_output_work_ewma_ms: float | None = None
    frame_seq: int = 0
    metadata_tracker: MetadataHysteresisTracker = field(default_factory=MetadataHysteresisTracker)
    source_identity_tracker: SourceIdentityTracker = field(default_factory=SourceIdentityTracker)
    process_worker_error: Exception | None = None
