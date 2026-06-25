"""Runtime loop worker for the mirroring pipeline."""

from __future__ import annotations

import logging
import time

import numpy as np

from nanoleaf_sync.capture.source_context import build_display_source_context
from nanoleaf_sync.config.presets import effective_drm_zone_patch_capture
from nanoleaf_sync.runtime.engine_frame import (
    _CAPTURE_CONTINUITY_GAP_S,
    _reset_pipeline_state,
    _resolve_capture_frame_dimensions,
)
from nanoleaf_sync.runtime.engine_loop_context import LoopPipelineContext
from nanoleaf_sync.runtime.fps_governor import capture_interval_budget_ms
from nanoleaf_sync.runtime.frame_context import build_frame_context
from nanoleaf_sync.runtime.ring_buf import CapturePayload
from nanoleaf_sync.runtime.startup import apply_current_thread_priority

logger = logging.getLogger(__name__)


def capture_worker_loop(ctx: LoopPipelineContext) -> None:

    apply_current_thread_priority(config=ctx.config, state=ctx.state, thread_label="capture worker")
    from nanoleaf_sync.runtime.fixed_timestep import FixedTimestepAccumulator

    capture_pacing = FixedTimestepAccumulator(1.0 / max(1.0, float(getattr(ctx.config, "fps", 60))))
    with ctx.metrics_lock:
        ctx.capture_worker_active = True
    while not ctx.state.stop_event.is_set():
        if ctx.state.reinit_pause.is_set() or ctx.state.is_reinitializing:
            ctx.state.capture_worker_idle.set()
            time.sleep(0.001)
            continue
        ctx.state.capture_worker_idle.set()
        if ctx.state.take_capture_buf_clear_request():
            ctx.capture_buf.clear()
        try:
            capture_pacing.tick()
            with ctx.gov_lock:
                gap_ewma = ctx.hid_output_work_ewma_ms
                target_fps_now = min(
                    max(1, int(getattr(ctx.config, "fps", 60))),
                    max(1, int(ctx.state.target_fps)),
                )
            capture_interval_ms = capture_interval_budget_ms(
                target_fps=target_fps_now,
                hid_output_work_ewma_ms=gap_ewma,
            )
            if capture_interval_ms is not None and ctx.last_capture_success_ts is not None:
                elapsed_ms = (time.perf_counter() - ctx.last_capture_success_ts) * 1000.0
                if elapsed_ms < capture_interval_ms * 0.95:
                    time.sleep(0.001)
                    continue
            cap = ctx.get_capture()
            if cap is None:
                ctx.state.capture_worker_idle.set()
                time.sleep(0.001)
                continue
            ctx.state.capture_worker_idle.clear()
            backend_name = str(getattr(cap, "name", "unknown"))
            backend_method = str(getattr(cap, "last_capture_path", "") or "")
            capture_start = time.perf_counter()
            zone_rects = list(ctx.state.latest_zone_rects_display)
            capture_result = None
            use_drm_rects = effective_drm_zone_patch_capture(
                drm_zone_patch_capture=bool(getattr(ctx.config, "drm_zone_patch_capture", False)),
                sync_mode=str(getattr(ctx.config, "sync_mode", "standard")),
            ) and bool(zone_rects)
            if use_drm_rects:
                capture_callable = cap.capture
                try:
                    capture_result = capture_callable(zone_rects=zone_rects)  # type: ignore[call-arg]
                except TypeError:
                    capture_result = capture_callable()
            else:
                capture_result = cap.capture()
            capture_end = time.perf_counter()
            call_ms = (capture_end - capture_start) * 1000.0
            with ctx.metrics_lock:
                ctx.latest_capture_backend_name = backend_name
                ctx.latest_capture_backend_method = str(
                    getattr(cap, "last_capture_path", "") or backend_method
                )
                ctx.capture_call_ms_latest = call_ms
                if ctx.last_capture_completed_ts is not None:
                    ctx.capture_worker_loop_gap_ms_latest = (
                        capture_end - ctx.last_capture_completed_ts
                    ) * 1000.0
                ctx.last_capture_completed_ts = capture_end
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
            frame_w, frame_h = _resolve_capture_frame_dimensions(
                frame=frame,
                precomputed=precomputed,
                capture_backend=cap,
                fallback_width=int(ctx.state.last_frame_width or 0),
                fallback_height=int(ctx.state.last_frame_height or 0),
            )
            if ctx.last_capture_success_ts is not None:
                capture_gap_s = capture_end - ctx.last_capture_success_ts
                if capture_gap_s > _CAPTURE_CONTINUITY_GAP_S:
                    _reset_pipeline_state(
                        state=ctx.state,
                        reason="capture_continuity_gap",
                        metadata_tracker=ctx.metadata_tracker,
                    )
            with ctx.metrics_lock:
                ctx.frame_seq += 1
                current_frame_seq = ctx.frame_seq
            display_source = build_display_source_context(
                cap,
                frame_width=frame_w,
                frame_height=frame_h,
            )
            frame_context = build_frame_context(
                frame_seq=current_frame_seq,
                captured_at=capture_end,
                source=display_source,
                frame_width=frame_w,
                frame_height=frame_h,
                precomputed_zone_colors=precomputed is not None,
                capture_duration_ms=call_ms,
            )
            if not ctx.capture_buf.try_push(
                CapturePayload(
                    captured_at=capture_end,
                    frame=frame,
                    precomputed_zone_colors=precomputed,
                    frame_context=frame_context,
                )
            ):
                logger.debug("capture worker: ring buffer full; dropping frame")
                with ctx.metrics_lock:
                    ctx.no_pending_frame_events += 1
                time.sleep(0.001)
            else:
                with ctx.metrics_lock:
                    if ctx.last_capture_success_ts is not None:
                        ctx.capture_success_interval_ms_latest = (
                            capture_end - ctx.last_capture_success_ts
                        ) * 1000.0
                    ctx.last_capture_success_ts = capture_end
            with ctx.metrics_lock:
                ctx.capture_worker_failures = 0
        except Exception as exc:
            with ctx.metrics_lock:
                ctx.capture_worker_failures += 1
                ctx.capture_worker_error_count += 1
            ctx.state.record_error(exc)
            logger.debug("capture worker error: %s", exc)
            time.sleep(0.005)
    with ctx.metrics_lock:
        ctx.capture_worker_active = False
