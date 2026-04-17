from __future__ import annotations

import logging
import time
from typing import Sequence

import numpy as np

from nanoleaf_sync.runtime.zones import zone_colors_array
from nanoleaf_sync.color.zone_mapper import resolve_device_zone_indices
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.runtime.startup import reinitialize_backends, should_reinitialize
from nanoleaf_sync.runtime.state import RGBTuple, RuntimeState, ZoneRect


logger = logging.getLogger(__name__)


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
) -> tuple[int, int, int, bool, tuple[int, ...]]:
    return (
        int(source_zone_count),
        int(config.device_zone_count),
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
) -> tuple[list[ZoneRect], np.ndarray]:
    zone_sig = _zones_signature(config, img_w, img_h)
    if state.zone_rects_signature != zone_sig or state.cached_zone_rects is None:
        state.cached_zone_rects = zones_from_config(config.zones, img_w, img_h)
        state.zone_rects_signature = zone_sig

    zones_px = state.cached_zone_rects
    source_zone_count = len(zones_px)

    mapping_sig = _mapping_signature(source_zone_count=source_zone_count, config=config)
    if (
        state.device_zone_mapping_signature != mapping_sig
        or state.cached_device_zone_indices is None
        or state.cached_device_zone_indices_np is None
    ):
        device_zone_count = int(config.device_zone_count) or source_zone_count
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
    zone_sampling_stride: int = 1,
) -> list[RGBTuple]:
    """
    Hot-path frame processing pipeline:
    capture frame -> zone colors -> map -> brightness/smoothing -> send-ready colors.
    """
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise RuntimeError(
            f"Capture returned unexpected frame shape: {getattr(frame, 'shape', None)}"
        )

    raw_colors = zone_colors_array(frame, zones_px, sample_step=zone_sampling_stride)
    if raw_colors.size == 0:
        return []

    mapped = raw_colors[np.asarray(device_zone_indices, dtype=np.intp)].astype(np.float32, copy=False)

    b = max(0.0, min(1.0, float(brightness)))
    if b != 1.0:
        mapped *= b

    a = max(0.0, min(1.0, float(smoothing)))
    if prev_smoothed_colors and a < 1.0:
        n = min(len(prev_smoothed_colors), mapped.shape[0])
        if n:
            prev_arr = np.asarray(prev_smoothed_colors[:n], dtype=np.float32)
            mapped[:n] = (a * mapped[:n]) + ((1.0 - a) * prev_arr)

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

    while not state.stop_event.is_set():
        start = time.perf_counter()

        try:
            capture = get_capture()
            driver = get_driver()
            frame = capture.capture()
            if frame is None:
                continue

            img_h, img_w, _ = frame.shape
            zones_px, device_zone_indices = _ensure_runtime_artifacts(
                state=state,
                config=config,
                img_w=img_w,
                img_h=img_h,
            )

            smoothed_colors = process_frame(
                frame=frame,
                prev_smoothed_colors=state.prev_smoothed_colors,
                zones_px=zones_px,
                device_zone_indices=device_zone_indices,
                brightness=config.brightness,
                smoothing=config.smoothing,
                zone_sampling_stride=config.zone_sampling_stride,
            )
            state.prev_smoothed_colors = smoothed_colors
            driver.send_frame(smoothed_colors)

            state.record_success()
            last_sent_zone_count = len(smoothed_colors)
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
            last_log = now
            elapsed_ms = (now - start) * 1000.0
            logger.info(
                "service_tick fps=%s elapsed_ms=%.2f zones=%s errors=%s",
                fps,
                elapsed_ms,
                last_sent_zone_count,
                state.consecutive_errors,
            )
            if config.verbose:
                print(
                    f"[service] tick fps={fps} elapsed_ms={elapsed_ms:.2f} zones={last_sent_zone_count}"
                )

        if now - next_deadline > interval_s:
            # Drop accumulated lag to keep output responsive under overload.
            next_deadline = now
        elif now < next_deadline:
            time.sleep(next_deadline - now)
