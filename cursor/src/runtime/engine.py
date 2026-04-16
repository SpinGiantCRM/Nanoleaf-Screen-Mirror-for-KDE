from __future__ import annotations

import logging
import time
from typing import Sequence, Tuple

from color.analyzer import zone_colors
from color.zone_mapper import map_colors_to_device_zones
from config import AppConfig
from runtime.processing import apply_brightness, ema_smooth, zones_from_config
from runtime.startup import reinitialize_backends, should_reinitialize
from runtime.state import RGBTuple, RuntimeState


logger = logging.getLogger(__name__)


def process_frame(
    *,
    frame,
    config: AppConfig,
    prev_smoothed_colors: Sequence[RGBTuple],
) -> list[RGBTuple]:
    """
    Hot-path frame processing pipeline:
    capture frame -> zone colors -> map -> brightness/smoothing -> send-ready colors.
    """
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise RuntimeError(
            f"Capture returned unexpected frame shape: {getattr(frame, 'shape', None)}"
        )

    img_h, img_w, _ = frame.shape
    zones_px = zones_from_config(config.zones, img_w, img_h)
    raw_colors = zone_colors(frame, zones_px)

    device_zone_count = config.device_zone_count or len(raw_colors)
    mapped_colors = map_colors_to_device_zones(
        raw_colors,
        device_zone_count=device_zone_count,
        zone_offset=config.zone_offset,
        reverse=config.reverse_zones,
        explicit_zone_map=config.explicit_zone_map or None,
    )

    bright_colors = apply_brightness(mapped_colors, config.brightness)
    return ema_smooth(prev_smoothed_colors, bright_colors, alpha=config.smoothing)


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
        if start < next_deadline:
            time.sleep(min(0.002, next_deadline - start))

        try:
            capture = get_capture()
            driver = get_driver()
            frame = capture.capture()
            if frame is None:
                continue

            smoothed_colors = process_frame(
                frame=frame,
                config=config,
                prev_smoothed_colors=state.prev_smoothed_colors,
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

        if now < next_deadline:
            time.sleep(next_deadline - now)
