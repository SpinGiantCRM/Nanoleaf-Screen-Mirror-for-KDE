from __future__ import annotations

import logging
import threading
import time

from nanoleaf_sync.capture.latency_probe import FrameTimingSample
from nanoleaf_sync.runtime.engine_frame import _reset_pipeline_state
from nanoleaf_sync.runtime.engine_loop_capture import capture_worker_loop
from nanoleaf_sync.runtime.engine_loop_context import LoopPipelineContext
from nanoleaf_sync.runtime.engine_loop_hid import hid_writer_loop
from nanoleaf_sync.runtime.engine_loop_process import process_worker_loop
from nanoleaf_sync.runtime.startup import reinitialize_backends, should_reinitialize

logger = logging.getLogger(__name__)


def run_loop_supervisor(ctx: LoopPipelineContext) -> None:
    threads = [
        threading.Thread(
            target=lambda: capture_worker_loop(ctx), name="capture-worker", daemon=True
        ),
        threading.Thread(
            target=lambda: process_worker_loop(ctx), name="process-worker", daemon=True
        ),
        threading.Thread(target=lambda: hid_writer_loop(ctx), name="hid-writer", daemon=True),
    ]
    for t in threads:
        t.start()

    # ---- supervisory loop ------------------------------------------------
    time.perf_counter()
    last_reinit_check = time.perf_counter()
    while not ctx.state.stop_event.is_set():
        time.sleep(0.05)
        now = time.perf_counter()

        # Startup timeout
        if not ctx.state.first_frame_sent and not ctx.state.startup_complete.is_set():
            startup_elapsed = now - ctx.startup_started_at
            ctx.state.startup_elapsed_ms = max(0.0, startup_elapsed * 1000.0)
            if startup_elapsed >= ctx.startup_frame_timeout_s:
                backend = ctx.latest_capture_backend_name or "unavailable"
                method = ctx.latest_capture_backend_method or "unavailable"
                if ctx.state.first_frame_seen and int(ctx.state.output_owner_dropped_frames) > 0:
                    reason = (
                        "Start failed before first frame: mirroring output is blocked "
                        f"(backend={backend}, method={method}). "
                        "Close Settings/setup preview and retry Start."
                    )
                    guidance = (
                        "Another exclusive LED output session is active, or mirroring "
                        "authorization expired after Stop. Press Start again after "
                        "closing setup tools."
                    )
                else:
                    reason = (
                        "Start failed before first frame: capture backend "
                        f"produced no frame within {ctx.startup_frame_timeout_s:.1f}s "
                        f"(backend={backend}, method={method})."
                    )
                    guidance = "Check capture backend readiness and retry."
                ctx.state.last_error = reason
                ctx.state.last_error_kind = "capture-timeout"
                ctx.state.last_error_guidance = guidance
                ctx.state.start_failure_reason = reason
                ctx.state.lifecycle_state = "failed"
                ctx.state.mark_startup(False)
                ctx.state.stop_event.set()
                break

        # Reinitialization check
        if now - last_reinit_check > 0.5:
            last_reinit_check = now
            with ctx.metrics_lock:
                worker_fails = ctx.capture_worker_failures
                proc_fails = ctx.process_worker_error_count
            if worker_fails >= ctx.error_limit or proc_fails >= ctx.error_limit:
                logger.warning(
                    "worker failures: capture=%d process=%d (limit=%d); "
                    "triggering reinitialization",
                    worker_fails,
                    proc_fails,
                    ctx.error_limit,
                )
                backoff_s = max(
                    0.0,
                    float(getattr(ctx.config, "reinit_backoff_ms", 500)) / 1000.0,
                )
                if should_reinitialize(
                    state=ctx.state,
                    error_limit=ctx.error_limit,
                    backoff_s=backoff_s,
                    now_ts=now,
                ):
                    reinitialize_backends(
                        install_drivers=ctx.install_drivers,
                        close_backends=ctx.close_backends,
                        state=ctx.state,
                    )
                    _reset_pipeline_state(
                        state=ctx.state,
                        reason="pipeline_reinit",
                        metadata_tracker=ctx.metadata_tracker,
                    )
                    with ctx.metrics_lock:
                        ctx.capture_worker_failures = 0
                        ctx.capture_worker_error_count = 0
                        ctx.process_worker_error_count = 0
            black_count = ctx.state.consecutive_black_frame_count()
            degrade_level = ctx.state.sync_black_frame_degradation(black_count)
            if degrade_level >= 2 and black_count >= 120 and black_count % 120 == 0:
                logger.warning(
                    "Sustained all-black capture (%d frames, degrade=%d); "
                    "skipping processing until capture recovers",
                    black_count,
                    degrade_level,
                )
            if ctx.state.take_black_frame_count_if_at_least(300):
                backoff_s = max(
                    0.0,
                    float(getattr(ctx.config, "reinit_backoff_ms", 500)) / 1000.0,
                )
                if should_reinitialize(
                    state=ctx.state,
                    error_limit=ctx.error_limit,
                    backoff_s=backoff_s,
                    now_ts=now,
                ):
                    logger.warning(
                        "Sustained all-black capture (>=300 frames); reinitializing backends"
                    )
                    reinitialize_backends(
                        install_drivers=ctx.install_drivers,
                        close_backends=ctx.close_backends,
                        state=ctx.state,
                    )
                    _reset_pipeline_state(
                        state=ctx.state,
                        reason="pipeline_reinit",
                        metadata_tracker=ctx.metadata_tracker,
                    )
    for t in threads:
        t.join(timeout=5.0)
        if t.is_alive():
            logger.warning(
                "%s thread did not exit within shutdown timeout (5s); "
                "it may still be blocked in IO",
                t.name,
            )
            ctx.state.stop_event.set()
            t.join(timeout=2.0)

    capture_dropped_delta = ctx.capture_buf.dropped_count()
    ctx.capture_buf.reset_dropped()
    process_dropped_delta = ctx.process_buf.dropped_count()
    ctx.process_buf.reset_dropped()
    dropped_delta = capture_dropped_delta + process_dropped_delta
    if dropped_delta > 0:
        ctx.state.latency_probe.add_stage_sample(
            FrameTimingSample(
                stage_ms={},
                target_fps=float(ctx.governor.target_fps),
                fps_cap=float(ctx.governor.target_fps),
                fps_cap_reason="FPS governor dynamic cap",
                dropped_or_skipped_frames_delta=dropped_delta,
                counters_delta={
                    "capture_buffer_dropped_frames": capture_dropped_delta,
                    "process_buffer_dropped_frames": process_dropped_delta,
                },
            )
        )
