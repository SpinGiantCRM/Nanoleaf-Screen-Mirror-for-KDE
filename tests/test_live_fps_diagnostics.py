from __future__ import annotations

from nanoleaf_sync.runtime.diagnostics_exports import latency_breakdown_lines


def _status_with_measurement(
    *, target_fps: float, effective_fps: float, include_cap: bool = True
) -> dict:
    return {
        "latency_measurement": {
            "live_mirroring_only": True,
            "target_fps": target_fps,
            "effective_output_fps": effective_fps,
            "fps_cap": target_fps if include_cap else 0.0,
            "fps_cap_reason": "UI FPS control cap" if include_cap else "",
            "dropped_or_skipped_frames": 2,
            "stages": {
                "loop_gap_ms": {
                    "available": True,
                    "median_ms": 8.40,
                    "p95_ms": 9.10,
                    "max_ms": 9.30,
                    "sample_count": 60,
                },
                "pacing_wait_ms": {
                    "available": True,
                    "median_ms": 0.80,
                    "p95_ms": 1.20,
                    "max_ms": 1.30,
                    "sample_count": 60,
                },
                "actual_work_ms": {
                    "available": True,
                    "median_ms": 6.70,
                    "p95_ms": 8.10,
                    "max_ms": 8.40,
                    "sample_count": 60,
                },
                "capture_wait_ms": {
                    "available": True,
                    "median_ms": 1.20,
                    "p95_ms": 2.30,
                    "max_ms": 2.50,
                    "sample_count": 60,
                },
                "capture_call_ms": {
                    "available": True,
                    "median_ms": 1.10,
                    "p95_ms": 2.20,
                    "max_ms": 2.40,
                    "sample_count": 60,
                },
                "capture_worker_loop_gap_ms": {
                    "available": True,
                    "median_ms": 8.10,
                    "p95_ms": 9.00,
                    "max_ms": 9.20,
                    "sample_count": 60,
                },
                "capture_success_interval_ms": {
                    "available": True,
                    "median_ms": 8.20,
                    "p95_ms": 9.10,
                    "max_ms": 9.30,
                    "sample_count": 60,
                },
                "frame_handoff_wait_ms": {
                    "available": True,
                    "median_ms": 0.30,
                    "p95_ms": 0.60,
                    "max_ms": 0.80,
                    "sample_count": 60,
                },
                "pending_frame_age_ms": {
                    "available": True,
                    "median_ms": 0.90,
                    "p95_ms": 1.20,
                    "max_ms": 1.40,
                    "sample_count": 60,
                },
                "frame_processing_ms": {
                    "available": True,
                    "median_ms": 2.40,
                    "p95_ms": 3.20,
                    "max_ms": 3.40,
                    "sample_count": 60,
                },
                "frame_convert_ms": {
                    "available": True,
                    "median_ms": 0.20,
                    "p95_ms": 0.30,
                    "max_ms": 0.35,
                    "sample_count": 60,
                },
                "zone_sampling_ms": {
                    "available": True,
                    "median_ms": 0.90,
                    "p95_ms": 1.20,
                    "max_ms": 1.30,
                    "sample_count": 60,
                },
                "colour_processing_ms": {
                    "available": True,
                    "median_ms": 0.80,
                    "p95_ms": 1.00,
                    "max_ms": 1.20,
                    "sample_count": 60,
                },
                "smoothing_ms": {
                    "available": True,
                    "median_ms": 0.25,
                    "p95_ms": 0.35,
                    "max_ms": 0.40,
                    "sample_count": 60,
                },
                "led_calibration_ms": {
                    "available": True,
                    "median_ms": 0.20,
                    "p95_ms": 0.30,
                    "max_ms": 0.40,
                    "sample_count": 60,
                },
                "output_prepare_ms": {
                    "available": True,
                    "median_ms": 0.10,
                    "p95_ms": 0.20,
                    "max_ms": 0.30,
                    "sample_count": 60,
                },
                "hid_write_ms": {
                    "available": True,
                    "median_ms": 0.60,
                    "p95_ms": 1.00,
                    "max_ms": 1.10,
                    "sample_count": 60,
                },
                "hid_device_write_ms": {
                    "available": True,
                    "median_ms": 0.60,
                    "p95_ms": 1.00,
                    "max_ms": 1.10,
                    "sample_count": 60,
                },
                "inferred_unattributed_gap_ms": {
                    "available": True,
                    "median_ms": 1.70,
                    "p95_ms": 2.00,
                    "max_ms": 2.20,
                    "sample_count": 60,
                },
            },
            "counters": {"no_pending_frame_ticks": 0, "capture_worker_error_count": 0},
            "flags": {"capture_worker_active": True},
            "labels": {
                "latest_capture_backend_name": "kwin-dbus",
                "hid_reports_per_frame": "3",
                "hid_bytes_per_report": "64",
                "hid_total_frame_bytes": "147",
                "hid_report_data_sizes": "64,64,19",
                "hid_per_report_write_ms": "5.7,5.8,5.9",
                "hid_write_blocking": "yes",
                "hid_write_retry_policy": "none",
                "hid_write_rate_limit_policy": "none",
                "hid_write_read_calls": "1",
                "hid_live_send_policy": "nonblocking_drain",
                "hid_response_wait_skipped": "yes",
            },
        }
    }


def test_live_fps_diagnostics_shows_configured_and_effective_fps() -> None:
    lines = latency_breakdown_lines(
        status=_status_with_measurement(target_fps=120.0, effective_fps=119.3)
    )
    assert any("configured_target_fps: 120.0" in line for line in lines)
    assert any("effective_output_fps: 119.3" in line for line in lines)
    assert any("frame_interval_target_ms:" in line for line in lines)


def test_live_fps_diagnostics_target_met_status_text() -> None:
    lines = latency_breakdown_lines(
        status=_status_with_measurement(target_fps=120.0, effective_fps=118.0)
    )
    assert any("120 FPS target is being met." in line for line in lines)


def test_live_fps_diagnostics_target_not_met_status_and_limiter_text() -> None:
    status = _status_with_measurement(target_fps=120.0, effective_fps=52.0)
    status["latency_measurement"]["stages"]["capture_wait_ms"]["median_ms"] = 16.5
    lines = latency_breakdown_lines(status=status)
    assert any("120 FPS target is not being met." in line for line in lines)
    assert any("Likely limiter:" in line for line in lines)


def test_limiter_inference_prefers_actual_work_over_scheduler_when_work_tracks_loop_gap() -> None:
    status = _status_with_measurement(target_fps=120.0, effective_fps=50.0)
    stages = status["latency_measurement"]["stages"]
    stages["loop_gap_ms"]["median_ms"] = 20.0
    stages["actual_work_ms"]["median_ms"] = 19.99
    stages["frame_processing_ms"]["median_ms"] = 9.07
    stages["hid_write_ms"]["median_ms"] = 7.64
    stages["pacing_wait_ms"] = {
        "available": False,
        "median_ms": 0.0,
        "p95_ms": 0.0,
        "max_ms": 0.0,
        "sample_count": 0,
    }
    lines = latency_breakdown_lines(status=status)
    assert any(
        "Likely limiter: actual work, dominated by frame processing + HID write." in line
        for line in lines
    )
    assert any("120 FPS budget: 8.33ms; actual work median: 19.99ms." in line for line in lines)
    assert any(
        "60 FPS budget: 16.67ms; frame processing + HID write median: 16.71ms." in line
        for line in lines
    )
    assert any(
        "frame_processing_ms + hid_write_ms exceeds the configured frame budget." in line
        for line in lines
    )


def test_scheduler_limiter_only_when_work_is_below_budget_but_loop_gap_is_high() -> None:
    status = _status_with_measurement(target_fps=120.0, effective_fps=70.0)
    stages = status["latency_measurement"]["stages"]
    stages["actual_work_ms"]["median_ms"] = 5.8
    stages["loop_gap_ms"]["median_ms"] = 14.5
    stages["pacing_wait_ms"]["median_ms"] = 3.8
    lines = latency_breakdown_lines(status=status)
    assert any("Likely limiter: pacing/scheduler." in line for line in lines)


def test_budget_comparison_highlights_frame_plus_hid_over_60_fps_budget() -> None:
    status = _status_with_measurement(target_fps=120.0, effective_fps=55.0)
    stages = status["latency_measurement"]["stages"]
    stages["frame_processing_ms"]["median_ms"] = 10.2
    stages["hid_write_ms"]["median_ms"] = 6.8
    lines = latency_breakdown_lines(status=status)
    assert any(
        "60 FPS budget: 16.67ms; frame processing + HID write median: 17.00ms." in line
        for line in lines
    )


def test_live_fps_diagnostics_no_samples_message() -> None:
    lines = latency_breakdown_lines(status={})
    assert lines == ["Start mirroring to measure live output FPS."]


def test_live_fps_diagnostics_cap_reason_is_displayed() -> None:
    lines = latency_breakdown_lines(
        status=_status_with_measurement(target_fps=120.0, effective_fps=90.0, include_cap=True)
    )
    assert any("Intentional FPS cap: 120.0 FPS (UI FPS control cap)." in line for line in lines)


def test_live_fps_diagnostics_excludes_manual_benchmark_contamination_message() -> None:
    lines = latency_breakdown_lines(
        status=_status_with_measurement(target_fps=120.0, effective_fps=119.0)
    )
    assert any("xdg-portal benchmark samples excluded" in line for line in lines)


def test_limiter_inference_prefers_capture_availability_when_unattributed_gap_is_large() -> None:
    status = _status_with_measurement(target_fps=120.0, effective_fps=12.8)
    stages = status["latency_measurement"]["stages"]
    stages["loop_gap_ms"]["median_ms"] = 78.0
    stages["actual_work_ms"]["median_ms"] = 18.0
    stages["capture_call_ms"]["median_ms"] = 58.0
    status["latency_measurement"]["counters"]["no_pending_frame_ticks"] = 80
    lines = latency_breakdown_lines(status=status)
    assert any("inferred_unattributed_gap_ms: 60.00" in line for line in lines)
    assert any("Likely limiter: capture-frame availability" in line for line in lines)
    assert any(
        "Gap attribution: runtime frequently had no pending captured frame" in line
        for line in lines
    )


def test_hid_budget_guidance_flags_120_and_60_when_device_write_is_too_slow() -> None:
    status = _status_with_measurement(target_fps=120.0, effective_fps=50.0)
    stages = status["latency_measurement"]["stages"]
    stages["hid_device_write_ms"]["median_ms"] = 17.4
    lines = latency_breakdown_lines(status=status)
    assert any("60 FPS cannot be reliably met due to HID write time" in line for line in lines)
    assert any("120 FPS cannot be met due to HID write time" in line for line in lines)


def test_hid_report_metadata_is_emitted_in_latency_breakdown() -> None:
    lines = latency_breakdown_lines(
        status=_status_with_measurement(target_fps=120.0, effective_fps=98.0)
    )
    assert any("hid_reports_per_frame: 3" in line for line in lines)
    assert any("hid_bytes_per_report: 64" in line for line in lines)
    assert any("hid_total_frame_bytes: 147" in line for line in lines)
    assert any("hid_per_report_write_ms: 5.7,5.8,5.9" in line for line in lines)
    assert any("hid_write_retry_policy: none" in line for line in lines)
    assert any("live_send_policy: nonblocking_drain" in line for line in lines)
    assert any("response_wait_skipped: yes" in line for line in lines)
