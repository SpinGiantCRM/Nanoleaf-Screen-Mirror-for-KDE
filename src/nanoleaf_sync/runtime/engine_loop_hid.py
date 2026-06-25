"""Runtime loop worker for the mirroring pipeline."""

from __future__ import annotations

import logging
import time

from nanoleaf_sync._coerce import as_rgb_tuple3, scalar_float
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
from nanoleaf_sync.runtime.engine_frame import (
    _WORKER_POLL_INTERVAL_S,
    _frame_context_latency_labels,
    _no_pending_frame_rate_per_second,
)
from nanoleaf_sync.runtime.engine_loop_context import LoopPipelineContext
from nanoleaf_sync.runtime.startup import apply_current_thread_priority

logger = logging.getLogger(__name__)


def _evaluate_stale_output_drop(**kwargs):
    from nanoleaf_sync.runtime.engine import evaluate_stale_output_drop

    return evaluate_stale_output_drop(**kwargs)


def hid_writer_loop(ctx: LoopPipelineContext) -> None:
    apply_current_thread_priority(config=ctx.config, state=ctx.state, thread_label="hid writer")
    sent_in_window = 0
    last_log = time.perf_counter()
    last_send_done_ts: float | None = None
    next_send_deadline_ts: float | None = None
    idle_poll_ms = _WORKER_POLL_INTERVAL_S * 1000.0

    while not ctx.state.stop_event.is_set():
        if ctx.state.reinit_pause.is_set() or ctx.state.is_reinitializing:
            ctx.state.hid_worker_idle.set()
            time.sleep(0.001)
            continue
        ctx.state.hid_worker_idle.set()
        try:
            payload = ctx.process_buf.pop_latest(timeout=_WORKER_POLL_INTERVAL_S)
            coalesced_sends = int(ctx.process_buf.last_pop_coalesced)
            now = time.perf_counter()

            if payload is None:
                # idle tick: update latency probe with idle stages only
                with ctx.metrics_lock:
                    cap_active = bool(ctx.capture_worker_active)
                    no_pending_events = ctx.no_pending_frame_events
                ctx.state.latency_probe.add_stage_sample(
                    FrameTimingSample(
                        stage_ms={
                            STAGE_CAPTURE_CALL: ctx.capture_call_ms_latest,
                            STAGE_RUNTIME_CAPTURE_CALL: ctx.capture_call_ms_latest,
                            STAGE_CAPTURE_WORKER_LOOP_GAP: ctx.capture_worker_loop_gap_ms_latest,
                            STAGE_CAPTURE_SUCCESS_INTERVAL: ctx.capture_success_interval_ms_latest,
                            STAGE_FRAME_HANDOFF_WAIT: None,
                            STAGE_FRAME_AVAILABLE_WAIT: idle_poll_ms,
                            STAGE_IDLE_WAIT: idle_poll_ms,
                            STAGE_RUNTIME_IDLE_WAIT: idle_poll_ms,
                            STAGE_FRAME_PROCESSING: None,
                            STAGE_ACTUAL_WORK: None,
                            STAGE_LOOP_GAP: None,
                        },
                        target_fps=float(ctx.governor.target_fps),
                        fps_cap=float(ctx.governor.target_fps),
                        fps_cap_reason="FPS governor dynamic cap",
                        dropped_or_skipped_frames_delta=0,
                        counters_delta={},
                        flags={"ctx.capture_worker_active": cap_active},
                        labels={
                            "ctx.latest_capture_backend_name": ctx.latest_capture_backend_name,
                            "capture_backend_method": ctx.latest_capture_backend_method,
                            "no_pending_frame_rate_per_second": (
                                _no_pending_frame_rate_per_second(
                                    no_pending_events, ctx.no_pending_started_at
                                )
                            ),
                        },
                    )
                )
                continue

            driver = ctx.get_driver()
            if driver is None:
                ctx.state.hid_worker_idle.set()
                continue
            if ctx.can_mirroring_write is not None and not ctx.can_mirroring_write():
                ctx.state.output_owner_dropped_frames += 1
                ctx.state.hid_worker_idle.set()
                continue
            ctx.state.hid_worker_idle.clear()

            pace_fps = min(
                max(1, int(getattr(ctx.config, "fps", 60))),
                max(1, int(ctx.governor.target_fps)),
            )
            if next_send_deadline_ts is not None and now < next_send_deadline_ts:
                wait_s = next_send_deadline_ts - now
                if wait_s > 0.0005:
                    time.sleep(min(wait_s, _WORKER_POLL_INTERVAL_S))
                continue

            if hasattr(driver, "_live_target_fps"):
                driver._live_target_fps = int(ctx.governor.target_fps)

            should_drop_stale, frame_age_ms, max_send_age_ms, stale_reason = (
                _evaluate_stale_output_drop(
                    captured_at=payload.captured_at,
                    now=now,
                    target_fps=float(pace_fps),
                    stale_frame_drop_enabled=bool(
                        getattr(ctx.config, "stale_frame_drop_enabled", True)
                    ),
                    min_max_send_age_ms=float(getattr(ctx.config, "min_max_send_age_ms", 60.0)),
                    max_send_age_frame_budget_multiplier=float(
                        getattr(ctx.config, "max_send_age_frame_budget_multiplier", 2.0)
                    ),
                )
            )
            if should_drop_stale:
                ctx.state.record_stale_output_drop(
                    frame_age_ms=frame_age_ms,
                    max_send_age_ms=max_send_age_ms,
                    reason=stale_reason,
                )
                with ctx.metrics_lock:
                    cap_active = bool(ctx.capture_worker_active)
                ctx.state.latency_probe.add_stage_sample(
                    FrameTimingSample(
                        stage_ms={
                            STAGE_PENDING_FRAME_AGE: frame_age_ms,
                        },
                        target_fps=float(ctx.governor.target_fps),
                        fps_cap=float(ctx.governor.target_fps),
                        fps_cap_reason="FPS governor dynamic cap",
                        dropped_or_skipped_frames_delta=1,
                        counters_delta={
                            "stale_output_dropped_frames": 1,
                        },
                        flags={"ctx.capture_worker_active": cap_active},
                        labels={
                            "stale_drop_reason": stale_reason,
                            "max_send_age_ms": f"{max_send_age_ms:.1f}",
                        },
                    )
                )
                continue

            outgoing_colors = [tuple(int(c) for c in row) for row in payload.smoothed_colors]
            if (
                ctx.state.first_frame_sent
                and ctx.state.prev_sent_colors
                and outgoing_colors == ctx.state.prev_sent_colors
            ):
                ctx.state.duplicate_output_skipped_frames += 1
                with ctx.metrics_lock:
                    cap_active = bool(ctx.capture_worker_active)
                ctx.state.latency_probe.add_stage_sample(
                    FrameTimingSample(
                        stage_ms={},
                        target_fps=float(ctx.governor.target_fps),
                        fps_cap=float(ctx.governor.target_fps),
                        fps_cap_reason="FPS governor dynamic cap",
                        dropped_or_skipped_frames_delta=1,
                        counters_delta={"duplicate_output_skipped_frames": 1},
                        flags={"ctx.capture_worker_active": cap_active},
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
                (payload.processing_timings.frame_convert_ms or 0.0)
                + (payload.processing_timings.zone_sampling_ms or 0.0)
                + (payload.processing_timings.colour_processing_ms or 0.0)
                + (payload.processing_timings.smoothing_ms or 0.0)
                + (payload.processing_timings.led_calibration_ms or 0.0)
                + (payload.processing_timings.output_prepare_ms or 0.0)
            )
            actual_work_ms = (send_done - now) * 1000.0
            loop_gap_ms = (
                (send_done - last_send_done_ts) * 1000.0 if last_send_done_ts is not None else None
            )
            if loop_gap_ms is not None:
                ctx.hid_loop_gap_ewma_ms = (
                    (0.9 * ctx.hid_loop_gap_ewma_ms) + (0.1 * loop_gap_ms)
                    if ctx.hid_loop_gap_ewma_ms is not None
                    else float(loop_gap_ms)
                )
            inferred_unattributed_gap_ms = (
                max(0.0, loop_gap_ms - actual_work_ms) if loop_gap_ms is not None else None
            )

            pace_fps = min(
                max(1, int(getattr(ctx.config, "fps", 60))),
                max(1, int(ctx.governor.target_fps)),
            )
            frame_budget_ms = 1000.0 / float(pace_fps)
            output_cycle_ms = float(actual_work_ms)
            ctx.hid_output_work_ewma_ms = (
                (0.9 * ctx.hid_output_work_ewma_ms) + (0.1 * output_cycle_ms)
                if ctx.hid_output_work_ewma_ms is not None
                else float(output_cycle_ms)
            )

            with ctx.metrics_lock:
                cap_active = bool(ctx.capture_worker_active)
                cap_error_now = int(ctx.capture_worker_error_count)

            pending_frame_age_ms = max(
                0.0,
                (time.perf_counter() - payload.captured_at) * 1000.0,
            )
            capture_to_send_ms = (send_done - payload.captured_at) * 1000.0
            ctx.ewma_capture_to_send_ms = (
                (0.9 * ctx.ewma_capture_to_send_ms) + (0.1 * capture_to_send_ms)
                if ctx.ewma_capture_to_send_ms > 0.0
                else capture_to_send_ms
            )

            with ctx.metrics_lock:
                no_pending_events = ctx.no_pending_frame_events
            capture_dropped_delta = ctx.capture_buf.dropped_count()
            ctx.capture_buf.reset_dropped()
            process_dropped_delta = ctx.process_buf.dropped_count()
            ctx.process_buf.reset_dropped()
            dropped_delta = capture_dropped_delta + process_dropped_delta + coalesced_sends

            ctx.state.latency_probe.add_stage_sample(
                FrameTimingSample(
                    stage_ms={
                        STAGE_CAPTURE_CALL: ctx.capture_call_ms_latest,
                        STAGE_RUNTIME_CAPTURE_CALL: ctx.capture_call_ms_latest,
                        STAGE_CAPTURE_WORKER_LOOP_GAP: ctx.capture_worker_loop_gap_ms_latest,
                        STAGE_CAPTURE_SUCCESS_INTERVAL: ctx.capture_success_interval_ms_latest,
                        STAGE_FRAME_HANDOFF_WAIT: None,
                        STAGE_FRAME_AVAILABLE_WAIT: None,
                        STAGE_PENDING_FRAME_AGE: pending_frame_age_ms,
                        STAGE_IDLE_WAIT: None,
                        STAGE_RUNTIME_IDLE_WAIT: None,
                        STAGE_FRAME_PROCESSING: frame_processing_ms,
                        STAGE_FRAME_CONVERT: payload.processing_timings.frame_convert_ms,
                        STAGE_ZONE_SAMPLING: payload.processing_timings.zone_sampling_ms,
                        STAGE_COLOUR_PROCESSING: payload.processing_timings.colour_processing_ms,
                        STAGE_SMOOTHING: payload.processing_timings.smoothing_ms,
                        STAGE_LED_CALIBRATION: payload.processing_timings.led_calibration_ms,
                        STAGE_OUTPUT_PREPARE: payload.processing_timings.output_prepare_ms,
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
                    target_fps=float(ctx.governor.target_fps),
                    fps_cap=float(ctx.governor.target_fps),
                    fps_cap_reason="FPS governor dynamic cap",
                    dropped_or_skipped_frames_delta=dropped_delta,
                    counters_delta={
                        "ctx.capture_worker_error_count": max(0, cap_error_now),
                        "capture_buffer_dropped_frames": capture_dropped_delta,
                        "process_buffer_dropped_frames": process_dropped_delta,
                        "coalesced_sends": coalesced_sends,
                    },
                    flags={"ctx.capture_worker_active": cap_active},
                    labels={
                        "ctx.latest_capture_backend_name": ctx.latest_capture_backend_name,
                        "capture_backend_method": ctx.latest_capture_backend_method,
                        **_frame_context_latency_labels(payload),
                        "no_pending_frame_rate_per_second": _no_pending_frame_rate_per_second(
                            no_pending_events, ctx.no_pending_started_at
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

            ctx.state.record_success()
            with ctx.state._lock:
                if payload.smooth_float_history:
                    ctx.state.prev_smooth_float_colors = [
                        (float(row[0]), float(row[1]), float(row[2]))
                        for row in payload.smooth_float_history
                    ]
                ctx.state.prev_sent_colors = [as_rgb_tuple3(row) for row in payload.smoothed_colors]
                ctx.state.prev_smoothed_colors = list(ctx.state.prev_sent_colors)
            ctx.state.first_frame_sent = True
            ctx.state.startup_elapsed_ms = max(
                0.0,
                (time.perf_counter() - ctx.startup_started_at) * 1000.0,
            )
            if not ctx.state.startup_complete.is_set():
                ctx.state.start_failure_reason = ""
                ctx.state.lifecycle_state = "running"
                ctx.state.mark_startup(True)
            ctx.last_sent_zone_count = len(payload.smoothed_colors)
            sent_in_window += 1

            # ---- adaptive FPS governor -----------------------------
            previous_target = ctx.governor.target_fps
            ctx.governor.record_frame(actual_work_ms)
            with ctx.gov_lock:
                ctx.state.target_fps = ctx.governor.target_fps
            ctx.state.governor_p95_latency_ms = scalar_float(
                ctx.governor.get_metrics().get("p95_latency_ms", 0.0)
            )
            ctx.state.latest_staleness_ms = float(capture_to_send_ms)
            ctx.state.output_healthy = output_cycle_ms <= (frame_budget_ms * 1.1)
            if ctx.governor.target_fps != previous_target:
                direction = "up" if ctx.governor.target_fps > previous_target else "down"
                logger.info(
                    "FPS ctx.governor: stepped %s %d → %d (p95_latency_ms=%.2f)",
                    direction,
                    previous_target,
                    ctx.governor.target_fps,
                    ctx.governor.get_metrics()["p95_latency_ms"],
                )
                if ctx.config.verbose:
                    print(
                        f"[service] FPS ctx.governor: stepped {direction} "
                        f"{previous_target} → {ctx.governor.target_fps} "
                        f"(p95_latency_ms={ctx.governor.get_metrics()['p95_latency_ms']:.2f})"
                    )

            # ---- adaptive pacing -----------------------------------
            budget_ms = frame_budget_ms
            pacing_wait_s = max(0.0, budget_ms / 1000.0 - actual_work_ms)
            if pacing_wait_s > 0.0:
                time.sleep(pacing_wait_s)
            last_send_done_ts = time.perf_counter()

            # Periodic status log
            if now - last_log > ctx.log_interval_s:
                window_s = max(0.001, now - last_log)
                send_fps_val = sent_in_window / window_s
                dropped_total = ctx.capture_buf.dropped_count()
                last_log = now
                sent_in_window = 0
                logger.info(
                    "service_tick seq=%s fps=%s elapsed_ms=%.2f "
                    "zones=%s errors=%s send_fps=%.1f "
                    "capture_to_send_ms=%.2f dropped_frames=%s",
                    getattr(payload.frame_context, "frame_seq", None)
                    if payload.frame_context is not None
                    else ctx.frame_seq,
                    ctx.governor.target_fps,
                    actual_work_ms,
                    ctx.last_sent_zone_count,
                    ctx.state.consecutive_errors,
                    send_fps_val,
                    ctx.ewma_capture_to_send_ms,
                    dropped_total,
                )
                if ctx.config.verbose:
                    print(
                        f"[service] tick fps={ctx.governor.target_fps} "
                        f"elapsed_ms={actual_work_ms:.2f} "
                        f"zones={ctx.last_sent_zone_count} "
                        f"send_fps={send_fps_val:.1f} "
                        f"capture_to_send_ms={ctx.ewma_capture_to_send_ms:.2f} "
                        f"dropped_frames={dropped_total}"
                    )
        except Exception as exc:
            ctx.state.record_error(exc)
            logger.debug("HID writer error: %s", exc)
