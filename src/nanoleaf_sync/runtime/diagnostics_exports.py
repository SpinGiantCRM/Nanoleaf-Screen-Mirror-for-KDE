from __future__ import annotations

import csv
import os
import struct
import tempfile
import time
import zlib
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.state import ZoneRect


def _format_latency_metric(value: object, *, precision: int = 1) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.{precision}f}"
    return "-"


def format_backend_attempt_row(row: dict[str, object]) -> str:
    backend = str(row.get("backend") or "unknown")
    status = str(row.get("status") or "skipped")
    mode = str(row.get("mode") or ("failed" if status == "failed" else "fresh-probe"))
    sample_count = int(row.get("sample_count") or 0)
    reason = str(row.get("reason") or "-")
    return (
        f"{backend}: status={status} mode={mode} samples={sample_count} "
        f"median={_format_latency_metric(row.get('median_ms'))} "
        f"p95={_format_latency_metric(row.get('p95_ms'))} "
        f"jitter={_format_latency_metric(row.get('jitter_ms'))} "
        f"score={_format_latency_metric(row.get('score'), precision=2)} "
        f"selected={'yes' if bool(row.get('selected')) else 'no'} "
        f"tentative={'yes' if bool(row.get('tentative')) else 'no'} "
        f"reason={reason}"
    )


def _normalize_side_counts(
    raw: object, *, source_zone_count: int
) -> tuple[int, int, int, int] | None:
    if not isinstance(raw, (tuple, list)) or len(raw) != 4:
        return None
    try:
        counts = tuple(max(0, int(i)) for i in raw)
    except (TypeError, ValueError):
        return None
    if sum(counts) <= 0 and source_zone_count > 0:
        return None
    return counts


def evaluate_geometry(*, status: dict, cfg: AppConfig) -> dict[str, object]:
    kde_w = int(status.get("kde_display_width") or 0)
    kde_h = int(status.get("kde_display_height") or 0)
    kde_scale = float(status.get("kde_scale_factor") or 0.0)
    cap_w = int(status.get("captured_frame_width") or status.get("capture_width") or 0)
    cap_h = int(status.get("captured_frame_height") or status.get("capture_height") or 0)
    expected_w = int(status.get("capture_width") or 0)
    expected_h = int(status.get("capture_height") or 0)

    physical_match = kde_w > 0 and kde_h > 0 and cap_w == kde_w and cap_h == kde_h
    logical_w = int(round(kde_w / kde_scale)) if kde_w > 0 and kde_scale > 0 else 0
    logical_h = int(round(kde_h / kde_scale)) if kde_h > 0 and kde_scale > 0 else 0
    logical_match = logical_w > 0 and logical_h > 0 and cap_w == logical_w and cap_h == logical_h
    expected_match = (
        expected_w > 0 and expected_h > 0 and cap_w == expected_w and cap_h == expected_h
    )
    inferred_scale = (float(kde_w) / float(cap_w)) if kde_w > 0 and cap_w > 0 else 0.0
    physical_aspect = (float(kde_w) / float(kde_h)) if kde_w > 0 and kde_h > 0 else 0.0
    capture_aspect = (float(cap_w) / float(cap_h)) if cap_w > 0 and cap_h > 0 else 0.0
    aspect_delta = (
        abs(physical_aspect - capture_aspect)
        if physical_aspect > 0.0 and capture_aspect > 0.0
        else None
    )

    coordinate_mode = "unknown"
    if physical_match:
        coordinate_mode = "physical"
    elif logical_match:
        coordinate_mode = "logical"
    elif expected_match or kde_w > 0 and cap_w > 0:
        coordinate_mode = "scaled"

    inferred_scale_sane = inferred_scale >= 1.1 and inferred_scale <= 16.0
    aspect_consistent = aspect_delta is not None and aspect_delta <= 0.03
    intentional_scaled = bool(
        expected_match and not physical_match and inferred_scale_sane and aspect_consistent
    )

    mismatch = bool(
        cap_w > 0
        and cap_h > 0
        and kde_w > 0
        and kde_h > 0
        and not physical_match
        and not logical_match
        and not expected_match
    )
    source_zone_count = int(status.get("source_zone_count") or 0)
    side_counts = _normalize_side_counts(
        status.get("source_zone_side_counts"), source_zone_count=source_zone_count
    )

    return {
        "kde_display_size": (kde_w, kde_h),
        "kde_scale_factor": kde_scale,
        "capture_backend": status.get("effective_capture_backend")
        or status.get("capture_backend")
        or "unknown",
        "captured_frame_size": (cap_w, cap_h),
        "expected_display_size": (expected_w, expected_h),
        "matches_physical": physical_match,
        "matches_logical": logical_match or expected_match,
        "inferred_scale_factor": inferred_scale if inferred_scale > 0 else None,
        "inferred_scale_sane": inferred_scale_sane,
        "expected_match": expected_match,
        "intentional_scaled_capture": intentional_scaled,
        "aspect_delta": aspect_delta,
        "coordinate_mode": coordinate_mode,
        "source_zone_count": source_zone_count,
        "strip_zone_count": int(
            status.get("configured_device_zone_count") or getattr(cfg, "device_zone_count", 0) or 0
        ),
        "side_counts": side_counts,
        "edge_thickness": status.get("edge_sampling_thickness"),
        "sample_step": int(
            status.get("zone_sampling_stride") or getattr(cfg, "zone_sampling_stride", 1) or 1
        ),
        "edge_locality": status.get("edge_locality") or getattr(cfg, "edge_locality", "balanced"),
        "display_preset": status.get("display_preset") or getattr(cfg, "display_preset", "hdr"),
        "hdr_enabled_assumed": str(getattr(cfg, "display_preset", "hdr")).lower() == "hdr",
        "geometry_warning": mismatch,
        "warning_text": (
            (
                f"Captured frame is scaled/downsampled from physical display "
                f"by {inferred_scale:.1f}x; sampling coordinates are scaled."
            )
            if intentional_scaled and inferred_scale > 0.0
            else (
                "Captured frame size does not match display geometry. "
                "Sampling positions may be scaled or offset."
            )
        ),
    }


def diagnostics_text_lines(*, status: dict, cfg: AppConfig) -> list[str]:
    geo = evaluate_geometry(status=status, cfg=cfg)
    side_counts = geo["side_counts"]
    side_counts_text = (
        f"{side_counts[0]}/{side_counts[1]}/{side_counts[2]}/{side_counts[3]}"
        if isinstance(side_counts, tuple)
        else "unavailable"
    )
    latency_lines = latency_breakdown_lines(status=status)
    return [
        f"KDE display resolution: {geo['kde_display_size'][0]}x{geo['kde_display_size'][1]}",
        f"KDE scale factor: {geo['kde_scale_factor'] or 'unknown'}",
        f"Selected backend: {geo['capture_backend']}",
        f"Captured frame size: {geo['captured_frame_size'][0]}x{geo['captured_frame_size'][1]}",
        f"Expected display size: "
        f"{geo['expected_display_size'][0]}x{geo['expected_display_size'][1]}",
        f"Match physical display: {'yes' if geo['matches_physical'] else 'no'}",
        f"Match logical/scaled display: {'yes' if geo['matches_logical'] else 'no'}",
        f"Inferred scale factor: {geo['inferred_scale_factor']:.3f}"
        if geo["inferred_scale_factor"]
        else "Inferred scale factor: unknown",
        f"Coordinate mode: {geo['coordinate_mode']}",
        f"Source-zone count: {geo['source_zone_count']} | "
        f"Strip LED zone count: {geo['strip_zone_count']}",
        f"Per-side zone counts (T/R/B/L): {side_counts_text}",
        f"Edge thickness: {geo['edge_thickness'] if geo['edge_thickness'] is not None else 'n/a'} "
        f"| sample_step: {geo['sample_step']} | edge locality: {geo['edge_locality']}",
        f"Light spread mode: {status.get('light_spread', 'balanced')}",
        f"Display preset: {geo['display_preset']} | "
        f"HDR enabled/assumed: {'yes' if geo['hdr_enabled_assumed'] else 'no'}",
        "Grey and white screen areas create neutral ambient light. Black areas turn the LEDs off.",
        geo["warning_text"]
        if geo["geometry_warning"] or bool(geo.get("intentional_scaled_capture"))
        else "Display geometry and capture frame space are consistent.",
        (
            "If per-zone output remains varied but the wall looks blended, "
            "this is likely physical diffusion."
        ),
        "If per-zone output is already flat, software processing/sampling spread is likely.",
        *latency_lines,
    ]


def latency_breakdown_lines(*, status: dict) -> list[str]:
    measurement = status.get("latency_measurement")
    if not isinstance(measurement, dict):
        return ["Start mirroring to measure live output FPS."]

    live_only = bool(measurement.get("live_mirroring_only", False))
    dropped = int(measurement.get("dropped_or_skipped_frames") or 0)
    counters = measurement.get("counters") if isinstance(measurement.get("counters"), dict) else {}
    flags = measurement.get("flags") if isinstance(measurement.get("flags"), dict) else {}
    labels = measurement.get("labels") if isinstance(measurement.get("labels"), dict) else {}
    target_fps = float(measurement.get("target_fps") or 0.0)
    effective_output_fps = float(measurement.get("effective_output_fps") or 0.0)
    fps_cap = float(measurement.get("fps_cap") or 0.0)
    fps_cap_reason = str(measurement.get("fps_cap_reason") or "none")
    stages = measurement.get("stages")
    if not isinstance(stages, dict):
        return ["Live output timing diagnostics unavailable (stage timing payload missing)."]
    frame_interval_target_ms = (1000.0 / target_fps) if target_fps > 0.0 else 0.0

    def _stage(stage_name: str) -> dict[str, float | int | bool]:
        row = stages.get(stage_name)
        if not isinstance(row, dict):
            return {"available": False, "median_ms": 0.0, "p95_ms": 0.0, "sample_count": 0}
        return {
            "available": bool(row.get("available", False)),
            "median_ms": float(row.get("median_ms") or 0.0),
            "p95_ms": float(row.get("p95_ms") or 0.0),
            "sample_count": int(row.get("sample_count") or 0),
        }

    loop_gap = _stage("loop_gap_ms")
    pacing_wait = _stage("pacing_wait_ms")
    actual_work = _stage("actual_work_ms")
    capture_wait = _stage("capture_wait_ms")
    capture_call = _stage("capture_call_ms")
    _stage("runtime_capture_call_ms")
    _stage("capture_worker_loop_gap_ms")
    _stage("capture_success_interval_ms")
    frame_handoff_wait = _stage("frame_handoff_wait_ms")
    _stage("pending_frame_age_ms")
    frame_processing = _stage("frame_processing_ms")
    hid_write = _stage("hid_write_ms")
    hid_device_write = _stage("hid_device_write_ms")
    _stage("inferred_unattributed_gap_ms")
    no_pending_frame_ticks = int(counters.get("no_pending_frame_ticks", 0) or 0)
    capture_worker_error_count = int(counters.get("capture_worker_error_count", 0) or 0)
    capture_worker_active = bool(flags.get("capture_worker_active", False))
    latest_capture_backend_name = str(
        labels.get("latest_capture_backend_name", "unavailable") or "unavailable"
    )
    capture_backend_method = str(labels.get("capture_backend_method", "") or "")
    benchmark_capture_ms = str(labels.get("benchmark_capture_ms", "") or "")
    no_pending_rate = str(labels.get("no_pending_frame_rate_per_second", "") or "")
    hid_device_write_limited = str(labels.get("hid_device_write_limited", "unknown") or "unknown")
    hid_reports_per_frame = str(labels.get("hid_reports_per_frame", "unavailable") or "unavailable")
    hid_bytes_per_report = str(labels.get("hid_bytes_per_report", "unavailable") or "unavailable")
    hid_total_frame_bytes = str(labels.get("hid_total_frame_bytes", "unavailable") or "unavailable")
    hid_report_data_sizes = str(labels.get("hid_report_data_sizes", "unavailable") or "unavailable")
    hid_per_report_write_ms = str(
        labels.get("hid_per_report_write_ms", "unavailable") or "unavailable"
    )
    hid_write_blocking = str(labels.get("hid_write_blocking", "unknown") or "unknown")
    hid_write_retry_policy = str(labels.get("hid_write_retry_policy", "unknown") or "unknown")
    hid_write_rate_limit_policy = str(
        labels.get("hid_write_rate_limit_policy", "unknown") or "unknown"
    )
    hid_write_read_calls = str(labels.get("hid_write_read_calls", "unavailable") or "unavailable")
    hid_live_send_policy = str(
        labels.get("hid_live_send_policy", "response_required") or "response_required"
    )
    hid_response_wait_skipped = str(labels.get("hid_response_wait_skipped", "no") or "no")

    target_met_threshold = max(1.0, target_fps * 0.95)
    target_met = target_fps > 0.0 and effective_output_fps >= target_met_threshold
    if target_met:
        status_line = f"{int(round(target_fps))} FPS target is being met."
    else:
        status_line = (
            f"{int(round(target_fps))} FPS target is not being met."
            if target_fps > 0.0
            else "FPS target is not configured."
        )

    frame_plus_hid_median = (
        float(frame_processing["median_ms"]) + float(hid_write["median_ms"])
        if frame_processing["available"] and hid_write["available"]
        else None
    )

    limiter_line = "Likely limiter: unavailable (insufficient stage data)."
    gap_attribution_line = "Gap attribution: unknown."
    budget_lines: list[str] = []
    if not target_met and target_fps > 0.0:
        actual_work_median = float(actual_work["median_ms"])
        loop_gap_median = float(loop_gap["median_ms"])
        pacing_wait_median = float(pacing_wait["median_ms"])
        pacing_is_negligible = (not pacing_wait["available"]) or pacing_wait_median <= 0.5
        work_tracks_loop_gap = (
            actual_work["available"]
            and loop_gap["available"]
            and abs(actual_work_median - loop_gap_median)
            <= max(1.0, 0.12 * max(actual_work_median, loop_gap_median))
        )
        actual_over_budget = (
            actual_work["available"] and actual_work_median > frame_interval_target_ms
        )
        work_under_budget_comfortably = actual_work["available"] and actual_work_median < (
            0.80 * frame_interval_target_ms
        )
        loop_gap_high = loop_gap["available"] and loop_gap_median > (
            1.15 * frame_interval_target_ms
        )
        unattributed_gap_ms = (
            max(0.0, loop_gap_median - actual_work_median)
            if loop_gap["available"] and actual_work["available"]
            else 0.0
        )

        configured_budget = frame_interval_target_ms
        if configured_budget > 0.0 and actual_work["available"]:
            budget_lines.append(
                f"{int(round(target_fps))} FPS budget: {configured_budget:.2f}ms; "
                f"actual work median: {actual_work_median:.2f}ms."
            )
        if frame_plus_hid_median is not None:
            for compare_fps in (120, 90, 60, 30):
                compare_budget = 1000.0 / float(compare_fps)
                if compare_fps == int(round(target_fps)) or compare_fps == 60:
                    budget_lines.append(
                        f"{compare_fps} FPS budget: {compare_budget:.2f}ms; "
                        f"frame processing + HID write median: "
                        f"{frame_plus_hid_median:.2f}ms."
                    )
            if frame_plus_hid_median > configured_budget:
                budget_lines.append(
                    "frame_processing_ms + hid_write_ms exceeds the configured frame budget."
                )

        if actual_over_budget and work_tracks_loop_gap and pacing_is_negligible:
            if frame_plus_hid_median is not None and frame_plus_hid_median >= (
                0.65 * actual_work_median
            ):
                limiter_line = (
                    "Likely limiter: actual work, dominated by frame processing + HID write."
                )
            else:
                limiter_line = "Likely limiter: actual work."
        elif work_under_budget_comfortably and loop_gap_high:
            limiter_line = "Likely limiter: pacing/scheduler."
        else:
            limiter_candidates: list[tuple[str, float]] = []
            if capture_wait["available"]:
                limiter_candidates.append(("capture", float(capture_wait["median_ms"])))
            if frame_processing["available"]:
                limiter_candidates.append(
                    ("frame processing", float(frame_processing["median_ms"]))
                )
            if hid_write["available"]:
                limiter_candidates.append(("HID write", float(hid_write["median_ms"])))
            if actual_work["available"]:
                limiter_candidates.append(("actual work", actual_work_median))
            if loop_gap_high and not actual_over_budget:
                limiter_candidates.append(
                    ("pacing/scheduler", loop_gap_median - frame_interval_target_ms)
                )
            if limiter_candidates:
                limiter_line = (
                    f"Likely limiter: {max(limiter_candidates, key=lambda item: item[1])[0]}."
                )

        if unattributed_gap_ms > 1.0:
            if no_pending_frame_ticks > 0:
                gap_attribution_line = (
                    "Gap attribution: runtime frequently had no pending captured frame; "
                    "output cadence is limited by frame availability/capture worker pace."
                )
                limiter_line = (
                    "Likely limiter: capture-frame availability (capture worker gap), "
                    "with secondary costs from zone sampling and HID write."
                )
            elif capture_call["available"] and capture_call["median_ms"] >= max(
                5.0, 0.65 * loop_gap_median
            ):
                gap_attribution_line = (
                    "Gap attribution: capture worker spends most of each cycle "
                    "inside capture.capture()."
                )
                limiter_line = "Likely limiter: capture backend call latency."
            elif frame_handoff_wait["available"] and frame_handoff_wait["median_ms"] > 1.0:
                gap_attribution_line = (
                    "Gap attribution: runtime spends measurable time waiting "
                    "on pending frame handoff."
                )
            elif pacing_wait["available"] and pacing_wait_median > 1.0:
                gap_attribution_line = (
                    "Gap attribution: scheduler/pacing sleep contributes to the gap."
                )
            else:
                gap_attribution_line = (
                    "Gap attribution: unattributed runtime gap remains; "
                    "inspect capture worker and scheduler metrics."
                )
        elif loop_gap_high and not actual_over_budget and pacing_wait["available"]:
            gap_attribution_line = (
                "Gap attribution: cadence mostly delayed by pacing/scheduler sleeps."
            )

    cap_line = "No intentional FPS cap reported."
    if fps_cap > 0.0:
        cap_line = f"Intentional FPS cap: {fps_cap:.1f} FPS ({fps_cap_reason})."

    lines = [
        "Live output timing samples (live mirroring only; xdg-portal benchmark samples excluded)."
        if live_only
        else "Live output timing samples (payload includes non-live data; inspect source).",
        f"configured_target_fps: {target_fps:.1f}",
        f"effective_output_fps: {effective_output_fps:.1f}",
        f"frame_interval_target_ms: {frame_interval_target_ms:.2f}",
        status_line,
        limiter_line,
        gap_attribution_line,
        cap_line,
        f"dropped/skipped frames: {dropped}",
        f"inferred_unattributed_gap_ms: "
        f"{max(0.0, float(loop_gap['median_ms']) - float(actual_work['median_ms'])):.2f}"
        if loop_gap["available"] and actual_work["available"]
        else "inferred_unattributed_gap_ms: unavailable",
        f"capture_worker_active: {'yes' if capture_worker_active else 'no'}",
        f"latest_capture_backend_name: {latest_capture_backend_name}",
        f"capture_backend_method: {capture_backend_method or 'unavailable'}",
        f"benchmark_capture_ms: {benchmark_capture_ms or 'unavailable'}",
        f"no_pending_frame_rate_per_second: {no_pending_rate or 'unavailable'}",
        f"no_pending_frame_ticks: {no_pending_frame_ticks}",
        f"capture_worker_error_count: {capture_worker_error_count}",
        f"configured_priority_mode: {status.get('configured_priority_mode', 'normal')}",
        f"effective_nice_value: {status.get('effective_nice_value', 'unavailable')}",
        f"priority_apply_status: {status.get('priority_apply_status', 'not_attempted')}",
        (
            f"priority_apply_error: {status.get('priority_apply_error')}"
            if str(status.get("priority_apply_error", "")).strip()
            else "priority_apply_error: none"
        ),
        (
            f"hid_frame_build_ms: unavailable "
            f"({labels.get('hid_frame_build_reason', 'not instrumented')})"
        ),
        (
            f"hid_flush_or_wait_ms: unavailable "
            f"({labels.get('hid_flush_or_wait_reason', 'not instrumented')})"
        ),
        f"hid_device_write_limited: {hid_device_write_limited}",
        f"hid_reports_per_frame: {hid_reports_per_frame}",
        f"hid_bytes_per_report: {hid_bytes_per_report}",
        f"hid_total_frame_bytes: {hid_total_frame_bytes}",
        f"hid_report_data_sizes: {hid_report_data_sizes}",
        f"hid_per_report_write_ms: {hid_per_report_write_ms}",
        f"hid_write_blocking: {hid_write_blocking}",
        f"hid_write_retry_policy: {hid_write_retry_policy}",
        f"hid_write_rate_limit_policy: {hid_write_rate_limit_policy}",
        f"hid_write_read_calls: {hid_write_read_calls}",
        f"live_send_policy: {hid_live_send_policy}",
        f"response_wait_skipped: {hid_response_wait_skipped}",
    ]
    lines.extend(budget_lines)
    if (
        target_fps >= 120.0
        and actual_work["available"]
        and float(actual_work["median_ms"]) > (1000.0 / 120.0)
    ):
        lines.append("120 FPS is over budget.")
    if actual_work["available"] and (1000.0 / 60.0) <= float(actual_work["median_ms"]) <= 20.0:
        lines.append("60 FPS is near target but currently slightly over budget.")
        lines.append("Try 60 FPS for stable use.")
    if hid_device_write["available"] and float(hid_device_write["median_ms"]) >= 5.0:
        lines.append(
            "HID path appears device-write limited "
            f"(hid_device_write_ms median ~{float(hid_device_write['median_ms']):.2f}ms)."
        )
    if hid_device_write["available"] and float(hid_device_write["median_ms"]) > (1000.0 / 60.0):
        lines.append(
            "60 FPS cannot be reliably met due to HID write time "
            "(hid_device_write_ms exceeds 16.67ms)."
        )
    if hid_device_write["available"] and float(hid_device_write["median_ms"]) > (1000.0 / 120.0):
        lines.append(
            "120 FPS cannot be met due to HID write time (hid_device_write_ms exceeds 8.33ms)."
        )

    def _format_stage_pair(label: str, stage_name: str) -> str:
        row = stages.get(stage_name)
        if not isinstance(row, dict) or not bool(row.get("available", False)):
            return f"{label}: unavailable"
        return (
            f"{label}: median={float(row.get('median_ms') or 0.0):.2f}ms "
            f"p95={float(row.get('p95_ms') or 0.0):.2f}ms"
        )

    lines.extend(
        [
            _format_stage_pair("loop_gap_ms", "loop_gap_ms"),
            _format_stage_pair("pacing_wait_ms", "pacing_wait_ms"),
            _format_stage_pair("actual_work_ms", "actual_work_ms"),
            _format_stage_pair("capture_wait_ms", "capture_wait_ms"),
            _format_stage_pair("capture_call_ms", "capture_call_ms"),
            _format_stage_pair("runtime_capture_call_ms", "runtime_capture_call_ms"),
            _format_stage_pair("capture_worker_loop_gap_ms", "capture_worker_loop_gap_ms"),
            _format_stage_pair("capture_success_interval_ms", "capture_success_interval_ms"),
            _format_stage_pair("frame_handoff_wait_ms", "frame_handoff_wait_ms"),
            _format_stage_pair("frame_available_wait_ms", "frame_available_wait_ms"),
            _format_stage_pair("runtime_idle_wait_ms", "runtime_idle_wait_ms"),
            _format_stage_pair("pending_frame_age_ms", "pending_frame_age_ms"),
            _format_stage_pair("frame_processing_ms", "frame_processing_ms"),
            _format_stage_pair("frame_convert_ms", "frame_convert_ms"),
            _format_stage_pair("zone_sampling_ms", "zone_sampling_ms"),
            _format_stage_pair("colour_processing_ms", "colour_processing_ms"),
            _format_stage_pair("smoothing_ms", "smoothing_ms"),
            _format_stage_pair("led_calibration_ms", "led_calibration_ms"),
            _format_stage_pair("output_prepare_ms", "output_prepare_ms"),
            _format_stage_pair("hid_write_ms", "hid_write_ms"),
            _format_stage_pair("hid_frame_build_ms", "hid_frame_build_ms"),
            _format_stage_pair("hid_device_write_ms", "hid_device_write_ms"),
            _format_stage_pair("hid_flush_or_wait_ms", "hid_flush_or_wait_ms"),
            _format_stage_pair("send_frame_total_ms", "hid_write_ms"),
            _format_stage_pair("inferred_unattributed_gap_ms", "inferred_unattributed_gap_ms"),
            _format_stage_pair("end_to_end_live_ms", "end_to_end_live_ms"),
        ]
    )
    return lines


def _png_pack(tag: bytes, data: bytes) -> bytes:
    chunk = tag + data
    return struct.pack("!I", len(data)) + chunk + struct.pack("!I", zlib.crc32(chunk) & 0xFFFFFFFF)


def write_png(path: Path, image_rgb: np.ndarray) -> None:
    h, w, _ = image_rgb.shape
    raw = b"".join(b"\x00" + image_rgb[y].astype(np.uint8).tobytes() for y in range(h))
    payload = b"\x89PNG\r\n\x1a\n"
    payload += _png_pack(b"IHDR", struct.pack("!2I5B", w, h, 8, 2, 0, 0, 0))
    payload += _png_pack(b"IDAT", zlib.compress(raw, 9))
    payload += _png_pack(b"IEND", b"")
    path.write_bytes(payload)


def _draw_rect(
    image: np.ndarray, rect: ZoneRect, color: tuple[int, int, int], thickness: int = 2
) -> None:
    x, y, w, h = rect
    x0 = max(0, int(x))
    y0 = max(0, int(y))
    x1 = min(image.shape[1], x0 + max(1, int(w)))
    y1 = min(image.shape[0], y0 + max(1, int(h)))
    if x1 <= x0 or y1 <= y0:
        return
    t = max(1, int(thickness))
    image[y0 : min(y1, y0 + t), x0:x1, :] = color
    image[max(y0, y1 - t) : y1, x0:x1, :] = color
    image[y0:y1, x0 : min(x1, x0 + t), :] = color
    image[y0:y1, max(x0, x1 - t) : x1, :] = color


def _zone_side_for_index(index: int, side_counts: tuple[int, int, int, int]) -> str:
    top, right, bottom, left = side_counts
    if index < top:
        return "top"
    if index < top + right:
        return "right"
    if index < top + right + bottom:
        return "bottom"
    if index < top + right + bottom + left:
        return "left"
    return "unknown"


def _synthetic_frame(width: int = 3840, height: int = 2160) -> np.ndarray:
    frame = np.full((height, width, 3), 40, dtype=np.uint8)
    frame[:, :, :] = np.array([96, 96, 96], dtype=np.uint8)
    return frame


def export_sampling_overlay(
    *,
    frame: np.ndarray | None,
    zones: Sequence[ZoneRect],
    side_counts: tuple[int, int, int, int],
    status: dict,
    cfg: AppConfig,
    synthetic: bool = False,
) -> Path:
    if not synthetic and not (isinstance(frame, np.ndarray) and frame.ndim == 3):
        raise ValueError(
            "No live frame available. Start mirroring or capture one diagnostic frame."
        )
    base = frame.copy() if isinstance(frame, np.ndarray) and frame.ndim == 3 else _synthetic_frame()
    side_palette = {
        "top": (0, 255, 0),
        "right": (32, 128, 255),
        "bottom": (255, 220, 0),
        "left": (255, 64, 64),
        "unknown": (255, 255, 255),
    }
    for idx, rect in enumerate(zones):
        side = _zone_side_for_index(idx, side_counts)
        _draw_rect(base, rect, side_palette[side], thickness=2)

    out_dir = Path(tempfile.gettempdir()) / "nanoleaf-kde-sync"
    out_dir.mkdir(parents=True, exist_ok=True)
    # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
    os.chmod(out_dir, 0o700)
    stamp = int(time.time())
    mode = "synthetic-test" if synthetic else "live-captured"
    path = out_dir / f"sampling-overlay-{mode}-{stamp}.png"
    write_png(path, base)
    os.chmod(path, 0o600)
    return path


def export_zone_report(*, rows: Sequence[dict[str, object]]) -> Path:
    if not rows:
        raise ValueError(
            "No per-zone diagnostics available. Start mirroring or capture one diagnostic frame."
        )
    out_dir = Path(tempfile.gettempdir()) / "nanoleaf-kde-sync"
    out_dir.mkdir(parents=True, exist_ok=True)
    # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
    os.chmod(out_dir, 0o700)
    path = out_dir / f"zone-report-{int(time.time())}.csv"
    base_fields = [
        "zone_index",
        "side",
        "pixel_rect",
        "sampled_rgb",
        "final_output_rgb",
        "mapped_physical_led_index",
    ]
    extra_fields = [
        "input_lightness",
        "output_lightness",
        "input_chroma",
        "output_chroma",
        "chroma_ratio",
        "neutral_floor_applied",
        "black_cutoff_applied",
        "grey_neutrality_verdict",
        "black_cutoff_verdict",
        "neutral_luminance_output_value",
    ]
    seen = set(base_fields)
    fields = list(base_fields)
    for key in extra_fields:
        if any(key in row for row in rows):
            fields.append(key)
            seen.add(key)
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})
    os.chmod(path, 0o600)
    return path


def export_latency_report(*, status: dict) -> Path:
    measurement = status.get("latency_measurement")
    if not isinstance(measurement, dict):
        raise ValueError(
            "No live latency diagnostics available. Start live mirroring to collect timing samples."
        )
    stages = measurement.get("stages")
    if not isinstance(stages, dict):
        raise ValueError("Latency diagnostics payload is malformed.")

    out_dir = Path(tempfile.gettempdir()) / "nanoleaf-kde-sync"
    out_dir.mkdir(parents=True, exist_ok=True)
    # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
    os.chmod(out_dir, 0o700)
    path = out_dir / f"latency-breakdown-{int(time.time())}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "stage",
                "available",
                "sample_count",
                "median_ms",
                "p95_ms",
                "max_ms",
                "live_mirroring_only",
                "target_fps",
                "fps_cap",
                "fps_cap_reason",
                "effective_output_fps",
                "dropped_or_skipped_frames",
            ],
        )
        writer.writeheader()
        for stage in (
            "capture_wait_ms",
            "capture_call_ms",
            "runtime_capture_call_ms",
            "capture_worker_loop_gap_ms",
            "capture_success_interval_ms",
            "frame_handoff_wait_ms",
            "frame_available_wait_ms",
            "pending_frame_age_ms",
            "pacing_wait_ms",
            "idle_wait_ms",
            "runtime_idle_wait_ms",
            "frame_processing_ms",
            "frame_convert_ms",
            "zone_sampling_ms",
            "colour_processing_ms",
            "smoothing_ms",
            "led_calibration_ms",
            "output_prepare_ms",
            "actual_work_ms",
            "hid_write_ms",
            "hid_frame_build_ms",
            "hid_device_write_ms",
            "hid_flush_or_wait_ms",
            "hid_ack_arrival_ms",
            "loop_gap_ms",
            "inferred_unattributed_gap_ms",
            "end_to_end_live_ms",
        ):
            row = stages.get(stage) or {}
            writer.writerow(
                {
                    "stage": stage,
                    "available": bool(row.get("available", False)),
                    "sample_count": int(row.get("sample_count", 0) or 0),
                    "median_ms": float(row.get("median_ms", 0.0) or 0.0),
                    "p95_ms": float(row.get("p95_ms", 0.0) or 0.0),
                    "max_ms": float(row.get("max_ms", 0.0) or 0.0),
                    "live_mirroring_only": bool(measurement.get("live_mirroring_only", False)),
                    "target_fps": float(measurement.get("target_fps", 0.0) or 0.0),
                    "fps_cap": float(measurement.get("fps_cap", 0.0) or 0.0),
                    "fps_cap_reason": str(measurement.get("fps_cap_reason", "") or ""),
                    "effective_output_fps": float(
                        measurement.get("effective_output_fps", 0.0) or 0.0
                    ),
                    "dropped_or_skipped_frames": int(
                        measurement.get("dropped_or_skipped_frames", 0) or 0
                    ),
                }
            )
    os.chmod(path, 0o600)
    return path


def default_kde_display_metadata() -> dict[str, object]:
    scale = os.environ.get("QT_SCALE_FACTOR") or os.environ.get("GDK_SCALE") or ""
    session = os.environ.get("XDG_SESSION_TYPE", "")
    return {
        "kde_scale_factor": float(scale) if scale else 0.0,
        "kde_display_width": 0,
        "kde_display_height": 0,
        "kde_session_type": session,
    }
