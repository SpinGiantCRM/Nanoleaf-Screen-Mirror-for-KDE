"""Frame-processing engine for the mirroring runtime loop.

The functions in this module transform captured RGB frames into device-zone
colors, apply brightness/smoothing, and handle runtime reinitialization hooks.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from nanoleaf_sync.runtime.zones import zone_colors_array
from nanoleaf_sync.color.zone_mapper import resolve_device_zone_indices
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.runtime.startup import reinitialize_backends, should_reinitialize
from nanoleaf_sync.runtime.state import RGBTuple, RuntimeState, ZoneRect


logger = logging.getLogger(__name__)


@dataclass
class PendingFrame:
    frame: np.ndarray
    captured_at: float


class PendingFrameSlot:
    """Single-slot latest-frame handoff with overwrite metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: PendingFrame | None = None
        self._ready = threading.Event()
        self.replaced_frames = 0

    def put_latest(self, frame: np.ndarray, captured_at: float) -> None:
        with self._lock:
            if self._pending is not None:
                self.replaced_frames += 1
            self._pending = PendingFrame(frame=frame, captured_at=captured_at)
            self._ready.set()

    def pop(self) -> PendingFrame | None:
        with self._lock:
            pending = self._pending
            self._pending = None
            self._ready.clear()
            return pending

    def wait(self, timeout: float) -> bool:
        return self._ready.wait(timeout=max(0.0, float(timeout)))


def _adaptive_one_euro_blend(
    *,
    current: np.ndarray,
    previous: np.ndarray,
    smoothing: float,
    smoothing_speed: float = 0.75,
) -> np.ndarray:
    """
    Adaptive smoothing blend inspired by the One Euro filter.

    `smoothing` remains user-facing in [0,1]:
    - 0.0: strongest smoothing at low motion
    - 1.0: effectively no smoothing
    """
    min_alpha = max(0.0, min(1.0, float(smoothing)))
    if min_alpha >= 1.0:
        return current

    velocity = np.abs(current - previous)
    # Scale 8-bit channel deltas into a 0..~1 adaptive range.
    speed_scale = max(0.01, float(smoothing_speed)) * 64.0
    speed = np.clip(velocity / speed_scale, 0.0, 1.0)
    alpha = min_alpha + (1.0 - min_alpha) * speed
    return alpha * current + (1.0 - alpha) * previous


def _zones_signature(config: AppConfig, img_w: int, img_h: int) -> tuple[int, int, tuple[tuple[float, float, float, float], ...]]:
    return (
        int(img_w),
        int(img_h),
        tuple((float(z.x), float(z.y), float(z.w), float(z.h)) for z in config.zones),
    )


def _mapping_signature(
    *,
    source_zone_count: int,
    config: AppConfig,
    detected_device_zone_count: int | None,
) -> tuple[int, int, int, int, bool, tuple[int, ...]]:
    return (
        int(source_zone_count),
        int(config.device_zone_count),
        int(detected_device_zone_count or 0),
        int(config.zone_offset),
        bool(config.reverse_zones),
        tuple(int(i) for i in (config.explicit_zone_map or [])),
    )


def _ensure_runtime_artifacts(
    *,
    state: RuntimeState,
    config: AppConfig,
    img_w: int,
    img_h: int,
    detected_device_zone_count: int | None = None,
) -> tuple[list[ZoneRect], np.ndarray]:
    zone_sig = _zones_signature(config, img_w, img_h)
    if state.zone_rects_signature != zone_sig or state.cached_zone_rects is None:
        state.cached_zone_rects = zones_from_config(config.zones, img_w, img_h)
        state.zone_rects_signature = zone_sig

    zones_px = state.cached_zone_rects
    source_zone_count = len(zones_px)

    mapping_sig = _mapping_signature(
        source_zone_count=source_zone_count,
        config=config,
        detected_device_zone_count=detected_device_zone_count,
    )
    if (
        state.device_zone_mapping_signature != mapping_sig
        or state.cached_device_zone_indices is None
        or state.cached_device_zone_indices_np is None
    ):
        configured_device_zone_count = int(config.device_zone_count)
        if configured_device_zone_count > 0:
            device_zone_count = configured_device_zone_count
        elif detected_device_zone_count is not None and int(detected_device_zone_count) > 0:
            device_zone_count = int(detected_device_zone_count)
        else:
            device_zone_count = source_zone_count
        state.cached_device_zone_indices = resolve_device_zone_indices(
            source_zone_count,
            device_zone_count=device_zone_count,
            zone_offset=config.zone_offset,
            reverse=config.reverse_zones,
            explicit_zone_map=config.explicit_zone_map or None,
        )
        state.cached_device_zone_indices_np = np.asarray(
            state.cached_device_zone_indices, dtype=np.intp
        )
        state.device_zone_mapping_signature = mapping_sig

    return zones_px, state.cached_device_zone_indices_np


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
    led_gamma: float = 2.2,
    color_mode: str = "balanced",
) -> list[RGBTuple]:
    """
    Hot-path frame processing pipeline:
    capture frame -> zone colors -> map -> brightness/smoothing -> send-ready colors.
    """
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise RuntimeError(
            f"Capture returned unexpected frame shape: {getattr(frame, 'shape', None)}"
        )

    raw_colors = zone_colors_array(
        frame,
        zones_px,
        sample_step=zone_sampling_stride,
        mode=color_mode,
        previous_zone_colors=prev_smoothed_colors,
    )
    if raw_colors.size == 0:
        return []

    if isinstance(device_zone_indices, np.ndarray):
        zone_indices = device_zone_indices
    else:
        zone_indices = np.asarray(device_zone_indices, dtype=np.intp)

    mapped = raw_colors[zone_indices].astype(np.float32, copy=False)

    b = max(0.0, min(1.0, float(brightness)))
    if b != 1.0:
        mapped *= b

    if prev_smoothed_colors:
        n = min(len(prev_smoothed_colors), mapped.shape[0])
        if n:
            prev_arr = np.asarray(prev_smoothed_colors[:n], dtype=np.float32)
            mapped[:n] = _adaptive_one_euro_blend(
                current=mapped[:n],
                previous=prev_arr,
                smoothing=smoothing,
                smoothing_speed=smoothing_speed,
            )

    gamma = max(1.0, min(4.0, float(led_gamma)))
    if abs(gamma - 2.2) > 1e-6:
        mapped = 255.0 * np.power(np.clip(mapped / 255.0, 0.0, 1.0), 1.0 / gamma)

    out = np.clip(np.rint(mapped), 0.0, 255.0).astype(np.uint8, copy=False)
    return [tuple(int(c) for c in row) for row in out.tolist()]


def run_loop(
    *,
    config: AppConfig,
    state: RuntimeState,
    get_capture,
    get_driver,
    install_drivers,
    close_backends,
) -> None:
    fps = max(1, int(config.fps))
    interval_s = 1.0 / fps

    next_deadline = time.perf_counter()
    last_log = 0.0
    log_interval_s = float(getattr(config, "status_log_interval_s", 5.0))
    last_sent_zone_count = 0
    sent_in_window = 0
    ewma_capture_to_send_ms = 0.0

    pending_slot = PendingFrameSlot()

    def _capture_worker() -> None:
        while not state.stop_event.is_set():
            try:
                if state.is_reinitializing:
                    time.sleep(0.001)
                    continue
                capture = get_capture()
                if capture is None:
                    time.sleep(0.001)
                    continue
                frame = capture.capture()
                if frame is None:
                    continue
                pending_slot.put_latest(frame=frame, captured_at=time.perf_counter())
            except Exception:
                # Main loop will handle backend reinitialization and logging.
                time.sleep(0.005)

    capture_thread = threading.Thread(target=_capture_worker, name="capture-worker", daemon=True)
    capture_thread.start()

    while not state.stop_event.is_set():
        start = time.perf_counter()
        processing_end = start
        skip_tick = False

        try:
            if state.is_reinitializing:
                skip_tick = True
            else:
                driver = get_driver()
                if driver is None:
                    skip_tick = True
                else:
                    pending = pending_slot.pop()
                    if pending is None:
                        wait_budget = max(0.0, min(interval_s, next_deadline - time.perf_counter()))
                        pending_slot.wait(timeout=min(0.005, wait_budget))
                        pending = pending_slot.pop()
                    if pending is None:
                        skip_tick = True
                    else:
                        frame = pending.frame
                        captured_at = pending.captured_at

            if skip_tick:
                pass
            else:
                assert frame is not None
                img_h, img_w, _ = frame.shape
                zones_px, device_zone_indices = _ensure_runtime_artifacts(
                    state=state,
                    config=config,
                    img_w=img_w,
                    img_h=img_h,
                    detected_device_zone_count=getattr(driver, "zone_count", None),
                )

                smoothed_colors = process_frame(
                    frame=frame,
                    prev_smoothed_colors=state.prev_smoothed_colors,
                    zones_px=zones_px,
                    device_zone_indices=device_zone_indices,
                    brightness=config.brightness,
                    smoothing=config.smoothing,
                    smoothing_speed=config.smoothing_speed,
                    zone_sampling_stride=config.zone_sampling_stride,
                    led_gamma=config.led_gamma,
                    color_mode=getattr(config, "color_mode", "balanced"),
                )
                state.prev_smoothed_colors = smoothed_colors
                driver.send_frame(smoothed_colors)
                processing_end = time.perf_counter()
                capture_to_send_ms = (processing_end - captured_at) * 1000.0
                ewma_capture_to_send_ms = (
                    (0.9 * ewma_capture_to_send_ms) + (0.1 * capture_to_send_ms)
                    if ewma_capture_to_send_ms > 0.0
                    else capture_to_send_ms
                )

                state.record_success()
                last_sent_zone_count = len(smoothed_colors)
                sent_in_window += 1
        except Exception as e:
            state.record_error(e)
            logger.warning("frame processing failed", exc_info=config.verbose)
            if config.verbose:
                print(f"[service] frame error #{state.consecutive_errors}: {e}")

            error_limit = max(1, int(getattr(config, "max_consecutive_errors", 5)))
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

        next_deadline += interval_s
        now = time.perf_counter()
        if now - last_log > log_interval_s:
            window_s = max(0.001, now - last_log)
            send_fps = sent_in_window / window_s
            last_log = now
            sent_in_window = 0
            elapsed_ms = (processing_end - start) * 1000.0
            logger.info(
                "service_tick fps=%s elapsed_ms=%.2f zones=%s errors=%s send_fps=%.1f capture_to_send_ms=%.2f replaced_frames=%s",
                fps,
                elapsed_ms,
                last_sent_zone_count,
                state.consecutive_errors,
                send_fps,
                ewma_capture_to_send_ms,
                pending_slot.replaced_frames,
            )
            if config.verbose:
                print(
                    f"[service] tick fps={fps} elapsed_ms={elapsed_ms:.2f} zones={last_sent_zone_count} send_fps={send_fps:.1f} capture_to_send_ms={ewma_capture_to_send_ms:.2f} replaced_frames={pending_slot.replaced_frames}"
                )

        if now - next_deadline > interval_s:
            # Drop accumulated lag to keep output responsive under overload.
            next_deadline = now
        elif now < next_deadline:
            time.sleep(next_deadline - now)

    capture_thread.join(timeout=0.2)
