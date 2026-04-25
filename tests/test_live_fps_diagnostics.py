from __future__ import annotations

from nanoleaf_sync.runtime.diagnostics_exports import latency_breakdown_lines


def _status_with_measurement(*, target_fps: float, effective_fps: float, include_cap: bool = True) -> dict:
    return {
        "latency_measurement": {
            "live_mirroring_only": True,
            "target_fps": target_fps,
            "effective_output_fps": effective_fps,
            "fps_cap": target_fps if include_cap else 0.0,
            "fps_cap_reason": "UI FPS control cap" if include_cap else "",
            "dropped_or_skipped_frames": 2,
            "stages": {
                "loop_gap_ms": {"available": True, "median_ms": 8.40, "p95_ms": 9.10, "max_ms": 9.30, "sample_count": 60},
                "pacing_wait_ms": {"available": True, "median_ms": 0.80, "p95_ms": 1.20, "max_ms": 1.30, "sample_count": 60},
                "actual_work_ms": {"available": True, "median_ms": 6.70, "p95_ms": 8.10, "max_ms": 8.40, "sample_count": 60},
                "capture_wait_ms": {"available": True, "median_ms": 1.20, "p95_ms": 2.30, "max_ms": 2.50, "sample_count": 60},
                "frame_processing_ms": {"available": True, "median_ms": 2.40, "p95_ms": 3.20, "max_ms": 3.40, "sample_count": 60},
                "hid_write_ms": {"available": True, "median_ms": 0.60, "p95_ms": 1.00, "max_ms": 1.10, "sample_count": 60},
            },
        }
    }


def test_live_fps_diagnostics_shows_configured_and_effective_fps() -> None:
    lines = latency_breakdown_lines(status=_status_with_measurement(target_fps=120.0, effective_fps=119.3))
    assert any("configured_target_fps: 120.0" in line for line in lines)
    assert any("effective_output_fps: 119.3" in line for line in lines)
    assert any("frame_interval_target_ms:" in line for line in lines)


def test_live_fps_diagnostics_target_met_status_text() -> None:
    lines = latency_breakdown_lines(status=_status_with_measurement(target_fps=120.0, effective_fps=118.0))
    assert any("120 FPS target is being met." in line for line in lines)


def test_live_fps_diagnostics_target_not_met_status_and_limiter_text() -> None:
    status = _status_with_measurement(target_fps=120.0, effective_fps=52.0)
    status["latency_measurement"]["stages"]["capture_wait_ms"]["median_ms"] = 16.5
    lines = latency_breakdown_lines(status=status)
    assert any("120 FPS target is not being met." in line for line in lines)
    assert any("Likely limiter:" in line for line in lines)


def test_live_fps_diagnostics_no_samples_message() -> None:
    lines = latency_breakdown_lines(status={})
    assert lines == ["Start mirroring to measure live output FPS."]


def test_live_fps_diagnostics_cap_reason_is_displayed() -> None:
    lines = latency_breakdown_lines(status=_status_with_measurement(target_fps=120.0, effective_fps=90.0, include_cap=True))
    assert any("Intentional FPS cap: 120.0 FPS (UI FPS control cap)." in line for line in lines)


def test_live_fps_diagnostics_excludes_manual_benchmark_contamination_message() -> None:
    lines = latency_breakdown_lines(status=_status_with_measurement(target_fps=120.0, effective_fps=119.0))
    assert any("xdg-portal benchmark samples excluded" in line for line in lines)
