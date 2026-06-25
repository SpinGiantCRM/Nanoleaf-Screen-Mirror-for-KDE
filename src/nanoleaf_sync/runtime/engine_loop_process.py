"""Runtime loop worker for the mirroring pipeline."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import cast

import numpy as np

from nanoleaf_sync._coerce import as_rgb_tuple3
from nanoleaf_sync.color._types import RGBTuple
from nanoleaf_sync.config.presets import is_accuracy_mode
from nanoleaf_sync.runtime.calibration_resolver import (
    CALIBRATION_INCOMPLETE_STATUS,
    evaluate_device_zone_authority,
    resolve_calibration_mapping_from_config,
)
from nanoleaf_sync.runtime.color_context import color_context_from_display_source
from nanoleaf_sync.runtime.color_pipeline import (
    build_pipeline_params_from_config,
    zone_centers_from_zones_px,
    zone_sample_motion,
)
from nanoleaf_sync.runtime.engine_frame import (
    _SHORT_BLACK_HOLD_MAX_FRAMES,
    _WORKER_POLL_INTERVAL_S,
    FrameProcessingTimings,
    _capture_backend_display_referred,
    _ensure_runtime_artifacts,
    _estimate_processing_staleness_ms,
    _reset_pipeline_state,
    _side_variance_diagnostics,
    _zone_sampling_diagnostic_fields,
    process_frame,
)
from nanoleaf_sync.runtime.engine_loop_context import LoopPipelineContext
from nanoleaf_sync.runtime.frame_context import FrameContext
from nanoleaf_sync.runtime.processing import scale_zones_to_display
from nanoleaf_sync.runtime.ring_buf import ProcessedPayload
from nanoleaf_sync.runtime.startup import apply_current_thread_priority

logger = logging.getLogger(__name__)


def process_worker_loop(ctx: LoopPipelineContext) -> None:
    apply_current_thread_priority(config=ctx.config, state=ctx.state, thread_label="process worker")
    while not ctx.state.stop_event.is_set():
        if ctx.state.reinit_pause.is_set() or ctx.state.is_reinitializing:
            ctx.state.process_worker_idle.set()
            time.sleep(0.001)
            continue
        ctx.state.process_worker_idle.set()
        if ctx.state.take_process_buf_clear_request():
            ctx.process_buf.clear()
        try:
            payload = ctx.capture_buf.pop_latest(timeout=_WORKER_POLL_INTERVAL_S)
            if payload is None:
                continue

            frame = payload.frame
            precomputed_zone_colors = payload.precomputed_zone_colors
            frame_context_obj = getattr(payload, "frame_context", None)
            frame_context = (
                frame_context_obj if isinstance(frame_context_obj, FrameContext) else None
            )
            captured_at = payload.captured_at
            ctx.state.first_frame_seen = True

            if frame is not None:
                img_h, img_w, _ = frame.shape
                mean_brightness = float(np.mean(frame))
            elif precomputed_zone_colors is not None:
                cap_for_dims = ctx.get_capture()
                cap_params = getattr(cap_for_dims, "params", None)
                img_w = int(getattr(cap_params, "width", ctx.state.last_frame_width or 480))
                img_h = int(getattr(cap_params, "height", ctx.state.last_frame_height or 270))
                mean_brightness = float(np.mean(precomputed_zone_colors))
            else:
                continue

            should_clear_smoothing = ctx.state.record_frame_brightness(
                mean_brightness,
                max_short_hold=_SHORT_BLACK_HOLD_MAX_FRAMES,
            )
            if mean_brightness < 2.0:
                black_count = ctx.state.consecutive_black_frame_count()
                degrade_level = ctx.state.sync_black_frame_degradation(black_count)
                if degrade_level >= 1 and ctx.state.first_frame_sent:
                    ctx.state.process_worker_idle.set()
                    continue
                if black_count > 0 and black_count % 60 == 0:
                    logger.warning(
                        "All-black frames: %d consecutive, "
                        "backend=%s, method=%s, mean_brightness=%.2f",
                        black_count,
                        ctx.latest_capture_backend_name,
                        ctx.latest_capture_backend_method,
                        mean_brightness,
                    )
            elif should_clear_smoothing:
                _reset_pipeline_state(
                    state=ctx.state,
                    reason="brightness_recovery",
                    buffers=False,
                )

            dimension_signature = (int(img_w), int(img_h))
            if (
                ctx.state.smoothing_dimension_signature is not None
                and ctx.state.smoothing_dimension_signature != dimension_signature
            ):
                _reset_pipeline_state(
                    state=ctx.state,
                    reason="frame_dimension_change",
                    buffers=False,
                )
            ctx.state.smoothing_dimension_signature = dimension_signature

            driver = ctx.get_driver()
            if driver is None:
                ctx.state.process_worker_idle.set()
                continue
            ctx.state.process_worker_idle.clear()

            detected_zones = getattr(
                driver,
                "reported_zone_count",
                getattr(driver, "zone_count", None),
            )
            zone_authority = evaluate_device_zone_authority(
                config=ctx.config,
                detected_device_zone_count=detected_zones,
            )
            ctx.state.device_zone_count_source = zone_authority.device_zone_count_source
            ctx.state.configured_device_zone_count = zone_authority.configured_device_zone_count
            ctx.state.detected_device_zone_count = zone_authority.detected_device_zone_count
            ctx.state.effective_device_zone_count = zone_authority.effective_device_zone_count
            ctx.state.device_zone_count_mismatch = zone_authority.device_zone_count_mismatch
            ctx.state.mapping_repair_required = zone_authority.mapping_repair_required
            ctx.state.device_zone_override_active = zone_authority.override_active
            if zone_authority.device_zone_count_mismatch and zone_authority.message:
                logger.warning(
                    "device zone count mismatch (using configured count): %s",
                    zone_authority.message,
                )

            zones_px, device_zone_indices = _ensure_runtime_artifacts(
                state=ctx.state,
                config=ctx.config,
                img_w=img_w,
                img_h=img_h,
                detected_device_zone_count=detected_zones,
            )

            if (
                ctx.state.calibration_status == CALIBRATION_INCOMPLETE_STATUS
                or len(device_zone_indices) <= 0
            ):
                mapping_snapshot = resolve_calibration_mapping_from_config(
                    config=ctx.config,
                    source_zone_count=len(zones_px),
                    detected_device_zone_count=detected_zones,
                )
                message = mapping_snapshot.status_message
                if len(device_zone_indices) <= 0 and "empty" not in message.lower():
                    message = f"{message} Derived device-zone mapping is empty."
                ctx.state.mark_calibration_incomplete(message)
                ctx.state.startup_elapsed_ms = max(
                    0.0,
                    (time.perf_counter() - ctx.startup_started_at) * 1000.0,
                )
                ctx.state.mark_startup(False)
                ctx.state.stop_event.set()
                logger.warning(
                    "calibration incomplete; screen mirroring will not stream frames: %s",
                    message,
                )
                break

            ctx.state.latest_zone_centers = zone_centers_from_zones_px(
                zones_px,
                frame_width=img_w,
                frame_height=img_h,
            )
            display_w = img_w
            display_h = img_h
            cap_for_display = ctx.get_capture()
            if cap_for_display is not None:
                drm_sampler = getattr(cap_for_display, "_drm_zone_sampler", None)
                if drm_sampler is not None:
                    display_w = int(getattr(drm_sampler, "width", display_w) or display_w)
                    display_h = int(getattr(drm_sampler, "height", display_h) or display_h)
            ctx.state.latest_zone_rects_display = scale_zones_to_display(
                zones_px,
                capture_width=img_w,
                capture_height=img_h,
                display_width=display_w,
                display_height=display_h,
            )

            build_diagnostics = bool(
                getattr(ctx.config, "verbose", False)
                or getattr(ctx.config, "live_diagnostics_enabled", False)
            )
            with ctx.metrics_lock:
                governor_target_fps = float(ctx.governor.target_fps)
                expected_hid_work_ms = ctx.hid_output_work_ewma_ms
            estimated_staleness_ms = _estimate_processing_staleness_ms(
                captured_at=captured_at,
                now=time.perf_counter(),
                hid_output_work_ewma_ms=expected_hid_work_ms,
            )
            cap_backend = ctx.get_capture()
            capture_backend_name = str(getattr(cap_backend, "name", "") or "")
            capture_display_referred = _capture_backend_display_referred(
                capture_backend_name,
                cap_backend,
            )
            skip_gamut = ctx.state.skip_display_gamut_adaptation
            color_context = None
            if frame_context is not None:
                source = frame_context.source
                prev_metadata_transitions = int(ctx.metadata_tracker.transitions)
                stabilized_meta = ctx.metadata_tracker.update(source.hdr_metadata)
                if stabilized_meta is not source.hdr_metadata:
                    source = replace(source, hdr_metadata=stabilized_meta)
                    frame_context = replace(frame_context, source=source)
                color_context = color_context_from_display_source(source)
                skip_gamut = bool(color_context.skip_display_gamut_adaptation)
                ctx.state.set_skip_display_gamut_adaptation(skip_gamut)
                capture_display_referred = bool(color_context.display_referred)
                identity, identity_changed = ctx.source_identity_tracker.observe(
                    source,
                    hdr_metadata_confidence=color_context.confidence,
                )
                ctx.state.capture_source_change_count = int(
                    ctx.source_identity_tracker.change_count
                )
                ctx.state.latest_capture_source_identity = {
                    **identity.as_dict(),
                    "change_count": ctx.source_identity_tracker.change_count,
                }
                ctx.state.metadata_hysteresis_transitions = int(ctx.metadata_tracker.transitions)
                if ctx.metadata_tracker.transitions > prev_metadata_transitions:
                    _reset_pipeline_state(
                        state=ctx.state,
                        reason="metadata_transition",
                        buffers=False,
                    )
                if identity_changed:
                    logger.warning("Capture source identity changed during mirroring session")
                    _reset_pipeline_state(
                        state=ctx.state,
                        reason="capture_source_identity_change",
                    )
                ctx.state.latest_frame_context = frame_context
                ctx.state.latest_color_context = color_context
                if ctx.state.first_frame_seen and not ctx.state.first_frame_sent:
                    ctx.state.lifecycle_state = "waiting_for_first_frame"
            elif cap_backend is not None:
                hdr_diag = getattr(cap_backend, "last_hdr_diagnostics", None) or {}
                if isinstance(hdr_diag, dict):
                    ctx.state.set_skip_display_gamut_adaptation(
                        bool(hdr_diag.get("skip_display_gamut_adaptation", False))
                    )
                    skip_gamut = bool(ctx.state.skip_display_gamut_adaptation)
            compositor_hdr_mode = bool(getattr(ctx.config, "compositor_hdr_mode", False))
            ctx.state.sdr_boost_compensation_enabled = compositor_hdr_mode
            if (
                capture_backend_name == "kwin-dbus"
                and compositor_hdr_mode
                and not ctx.state.kwin_screenshot2_hdr_warning_logged
            ):
                logger.warning("Screen capture via Screenshot2 cannot preserve HDR color accuracy")
                ctx.state.kwin_screenshot2_hdr_warning_logged = True
            pipeline_params = build_pipeline_params_from_config(
                ctx.config,
                return_diagnostics=True,
                build_zone_diagnostics=build_diagnostics,
                skip_display_gamut_adaptation=skip_gamut,
                sdr_boost_compensation_enabled=ctx.state.sdr_boost_compensation_enabled,
                capture_display_referred=capture_display_referred,
                effective_target_fps=governor_target_fps,
                config_fps=float(getattr(ctx.config, "fps", 60)),
                staleness_ms=estimated_staleness_ms,
                output_healthy=bool(ctx.state.output_healthy),
                prev_sampled_zone_colors=ctx.state.prev_sampled_zone_colors,
                previous_palette_algorithms=ctx.state.prev_palette_algorithms,
                zone_palette_temporal_states=ctx.state.zone_palette_temporal_states,
                palette_frame_index=int(ctx.state.palette_frame_index),
                stabilize_palette_selection=not is_accuracy_mode(
                    bool(getattr(ctx.config, "accuracy_mode", False)),
                    str(getattr(ctx.config, "color_style", "natural")),
                ),
                prior_zone_sample_motion=float(ctx.state.prior_zone_sample_motion),
                prior_area_average_mode=bool(ctx.state.prior_area_average_mode),
                sampling_mode_dwell_remaining=int(ctx.state.sampling_mode_dwell_remaining),
                color_context=color_context,
                dark_zone_stabilize_hold=ctx.state.dark_zone_stabilize_hold,
                blend_hysteresis=ctx.state.blend_hysteresis_state,
                output_quantization_prev_hold=ctx.state.output_quantization_prev_hold,
                prev_zone_variance=ctx.state.per_zone_variance,
                virtual_oversample=int(getattr(ctx.config, "virtual_zone_oversample", 0) or 0),
                scene_adaptive_profiles=bool(getattr(ctx.config, "scene_adaptive_profiles", False)),
            )
            light_spread = pipeline_params.light_spread
            if ctx.state.flattening_mitigation_active:
                light_spread = "off"
            with ctx.state._lock:
                prev_sent_snapshot = list(ctx.state.prev_sent_colors)
                prev_smooth_snapshot = list(ctx.state.prev_smooth_float_colors)
                prev_smoothed_snapshot = list(ctx.state.prev_smoothed_colors)
            processed = cast(
                tuple[
                    list[RGBTuple],
                    np.ndarray,
                    np.ndarray,
                    np.ndarray,
                    FrameProcessingTimings,
                    list[tuple[float, float, float]],
                    list[RGBTuple],
                ],
                process_frame(
                    frame=frame,
                    precomputed_zone_colors=precomputed_zone_colors,
                    prev_smoothed_colors=prev_sent_snapshot or prev_smoothed_snapshot,
                    prev_smooth_float_colors=prev_smooth_snapshot
                    or [(float(r), float(g), float(b)) for r, g, b in prev_smoothed_snapshot],
                    prev_sent_colors=prev_sent_snapshot or prev_smoothed_snapshot,
                    zones_px=zones_px,
                    device_zone_indices=device_zone_indices,  # type: ignore[arg-type]
                    compositor_hdr_mode=pipeline_params.compositor_hdr_mode,
                    sdr_boost_nits=pipeline_params.sdr_boost_nits,
                    hdr_max_nits=pipeline_params.hdr_max_nits,
                    sdr_boost_compensation_enabled=(pipeline_params.sdr_boost_compensation_enabled),
                    accuracy_mode=pipeline_params.accuracy_mode,
                    skip_display_gamut_adaptation=pipeline_params.skip_display_gamut_adaptation,
                    brightness=pipeline_params.brightness,
                    smoothing=pipeline_params.smoothing,
                    smoothing_speed=pipeline_params.smoothing_speed,
                    zone_sampling_stride=pipeline_params.zone_sampling_stride,
                    zone_sampling_engine=pipeline_params.zone_sampling_engine,
                    motion_preset=pipeline_params.motion_preset,
                    light_spread=light_spread,
                    color_style=pipeline_params.color_style,
                    edge_locality=pipeline_params.edge_locality,
                    sampling_mode=pipeline_params.sampling_mode,
                    letterbox_detection=pipeline_params.letterbox_detection,
                    led_calibration=pipeline_params.led_calibration,
                    sync_mode=pipeline_params.sync_mode,
                    predictive_sync_strength=pipeline_params.predictive_sync_strength,
                    effective_target_fps=pipeline_params.effective_target_fps,
                    config_fps=pipeline_params.config_fps,
                    staleness_ms=pipeline_params.staleness_ms,
                    output_healthy=pipeline_params.output_healthy,
                    sampling_quality=pipeline_params.sampling_quality,
                    prev_sampled_zone_colors=pipeline_params.prev_sampled_zone_colors,
                    previous_palette_algorithms=pipeline_params.previous_palette_algorithms,
                    prior_zone_sample_motion=pipeline_params.prior_zone_sample_motion,
                    prior_area_average_mode=pipeline_params.prior_area_average_mode,
                    return_diagnostics=True,
                    build_zone_diagnostics=build_diagnostics,
                ),
            )
            (
                smoothed_colors,
                sampled_zone_colors,
                pre_led_colors,
                final_zone_colors,
                processing_timings,
                smooth_float_history,
                sent_history,
            ) = processed

            if (
                mean_brightness < 2.0
                and 0 < ctx.state.consecutive_black_frame_count() <= _SHORT_BLACK_HOLD_MAX_FRAMES
                and prev_sent_snapshot
                and ctx.state.first_frame_sent
            ):
                smoothed_colors = [
                    (int(row[0]), int(row[1]), int(row[2])) for row in prev_sent_snapshot
                ]

            ctx.state.predictive_sync_active = bool(
                getattr(processing_timings, "predictive_sync_active", False)
            )
            ctx.state.predictive_lookahead_frames = float(
                getattr(processing_timings, "predictive_lookahead_frames", 0.0) or 0.0
            )
            ctx.state.predictive_scene_cut_suppressed = bool(
                getattr(processing_timings, "predictive_scene_cut_suppressed", False)
            )
            ctx.state.prior_area_average_mode = bool(
                getattr(processing_timings, "area_average_active", False)
            )
            ctx.state.sampling_mode_dwell_remaining = int(
                getattr(processing_timings, "sampling_mode_dwell_remaining", 0) or 0
            )
            per_zone_variance = getattr(processing_timings, "per_zone_variance", ())
            if per_zone_variance:
                ctx.state.per_zone_variance = np.asarray(per_zone_variance, dtype=np.float32)
            dark_hold = getattr(processing_timings, "dark_zone_stabilize_hold", ())
            if dark_hold:
                ctx.state.dark_zone_stabilize_hold = [bool(v) for v in dark_hold]
            blend_hyst = getattr(processing_timings, "blend_hysteresis", None)
            if blend_hyst is not None:
                ctx.state.blend_hysteresis_state = blend_hyst
            quant_hold = getattr(processing_timings, "output_quantization_prev_hold", ())
            if quant_hold:
                ctx.state.output_quantization_prev_hold = [bool(v) for v in quant_hold]
            prev_samples = list(ctx.state.prev_sampled_zone_colors or [])
            ctx.state.prior_zone_sample_motion = zone_sample_motion(
                np.asarray(sampled_zone_colors, dtype=np.uint8),
                prev_samples or None,
            )
            ctx.governor.signal_motion(ctx.state.prior_zone_sample_motion)
            ctx.state.motion_envelope = float(ctx.governor.motion_envelope)
            ctx.state.prev_sampled_zone_colors = [
                as_rgb_tuple3(row)
                for row in np.asarray(sampled_zone_colors, dtype=np.uint8).tolist()
            ]
            palette_modes = getattr(processing_timings, "per_zone_sampling_mode", ()) or ()
            ctx.state.prev_palette_algorithms = [str(v) for v in palette_modes]
            temporal_states = (
                getattr(processing_timings, "per_zone_palette_temporal_states", ()) or ()
            )
            ctx.state.zone_palette_temporal_states = [dict(row) for row in temporal_states]
            ctx.state.palette_frame_index += 1
            ctx.state.first_frame_processed = True
            ctx.state.last_frame_width = int(img_w)
            ctx.state.last_frame_height = int(img_h)
            if frame is not None:
                ctx.state.latest_frame_rgb = frame
            ctx.state.latest_zones_px = list(zones_px)

            side_var = _side_variance_diagnostics(
                sampled=sampled_zone_colors,
                final=final_zone_colors,
                side_counts=ctx.state.latest_zone_side_counts,
            )
            ctx.state.latest_side_variance_diagnostics = side_var
            ctx.state.flattening_mitigation_active = any(
                bool(side.get("processing_flattened", False)) for side in side_var.values()
            )

            zone_diagnostics: list[dict[str, object]] = []
            if build_diagnostics:
                from nanoleaf_sync.runtime.colour_path_diagnostics import (
                    build_zone_colour_path_row,
                    resolve_mapped_led_index,
                    resolve_zone_side,
                )

                proc_timings = (
                    processing_timings
                    if isinstance(processing_timings, FrameProcessingTimings)
                    else None
                )
                for zone_index, rect in enumerate(zones_px):
                    sampled_rgb = as_rgb_tuple3(
                        np.asarray(sampled_zone_colors[zone_index], dtype=np.uint8).tolist()
                    )
                    mapped_led_index = resolve_mapped_led_index(
                        zone_index,
                        device_zone_indices,
                    )
                    if mapped_led_index is None:
                        pre_led_rgb = sampled_rgb
                        final_rgb = sampled_rgb
                    else:
                        pre_led_rgb = as_rgb_tuple3(
                            np.asarray(pre_led_colors[mapped_led_index], dtype=np.uint8).tolist()
                        )
                        final_rgb = as_rgb_tuple3(
                            np.asarray(final_zone_colors[mapped_led_index], dtype=np.uint8).tolist()
                        )
                    side = resolve_zone_side(
                        zone_index,
                        ctx.state.latest_zone_side_counts,
                    )
                    zone_diagnostics.append(
                        build_zone_colour_path_row(
                            zone_index=zone_index,
                            rect=rect,
                            side=side,
                            sampled_rgb=sampled_rgb,
                            mapped_led_index=mapped_led_index,
                            pre_led_rgb=pre_led_rgb,
                            final_rgb=final_rgb,
                            proc_timings=proc_timings,
                            sampling_fields=_zone_sampling_diagnostic_fields(
                                zone_index=zone_index,
                                default_rect=rect,
                                proc_timings=proc_timings,
                            ),
                            color_style=str(getattr(ctx.config, "color_style", "reference")),
                        )
                    )
                for row in zone_diagnostics:
                    side_key = str(row.get("side"))
                    side_stats = side_var.get(side_key)
                    row["side_variance"] = side_stats if isinstance(side_stats, dict) else {}
                    row["processing_flattened_side"] = bool(
                        row["side_variance"].get("processing_flattened", False)
                        if isinstance(row["side_variance"], dict)
                        else False
                    )
                ctx.state.latest_zone_diagnostics = zone_diagnostics

            replaced_queued_processed_frame = ctx.process_buf.push_latest(
                ProcessedPayload(
                    smoothed_colors=smoothed_colors,
                    smooth_float_history=smooth_float_history,
                    sent_history=sent_history,
                    captured_at=captured_at,
                    zones_px=list(zones_px),
                    device_zone_indices=device_zone_indices,
                    sampled_zone_colors=sampled_zone_colors,
                    pre_led_colors=pre_led_colors,
                    final_zone_colors=final_zone_colors,
                    processing_timings=processing_timings,
                    zone_diagnostics=zone_diagnostics,
                    side_var=side_var,
                    frame_context=frame_context,
                    color_context=color_context,
                )
            )
            if replaced_queued_processed_frame:
                logger.debug("process worker: replaced stale processed frame queued for HID writer")
                time.sleep(0.001)
            else:
                time.sleep(0.001)
            ctx.process_worker_error = None
            with ctx.metrics_lock:
                ctx.process_worker_error_count = 0
        except Exception as exc:
            ctx.process_worker_error = exc
            with ctx.metrics_lock:
                ctx.process_worker_error_count += 1
            ctx.state.record_error(exc)
            logger.debug("process worker error: %s", exc)
            time.sleep(0.001)
