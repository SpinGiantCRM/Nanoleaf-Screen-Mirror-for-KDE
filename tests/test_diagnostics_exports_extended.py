"""Tests for diagnostics_exports.py pure functions."""

from __future__ import annotations

import numpy as np
import pytest

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.diagnostics_exports import (
    _format_latency_metric,
    _normalize_side_counts,
    _zone_side_for_index,
    _png_pack,
    _draw_rect,
    _synthetic_frame,
    diagnostics_text_lines,
    evaluate_geometry,
    format_backend_attempt_row,
    latency_breakdown_lines,
    default_kde_display_metadata,
)


# ---------------------------------------------------------------------------
# _format_latency_metric
# ---------------------------------------------------------------------------


def test_format_latency_metric_float() -> None:
    assert _format_latency_metric(12.3456, precision=1) == "12.3"
    assert _format_latency_metric(12.3456, precision=2) == "12.35"


def test_format_latency_metric_int() -> None:
    assert _format_latency_metric(42) == "42.0"


def test_format_latency_metric_none() -> None:
    assert _format_latency_metric(None) == "-"


def test_format_latency_metric_string() -> None:
    assert _format_latency_metric("hello") == "-"


# ---------------------------------------------------------------------------
# format_backend_attempt_row
# ---------------------------------------------------------------------------


def test_format_backend_attempt_row_basic() -> None:
    row = {
        "backend": "kwin-dbus",
        "status": "tested",
        "mode": "fresh-probe",
        "sample_count": 10,
        "median_ms": 5.2,
        "p95_ms": 8.1,
        "jitter_ms": 2.3,
        "score": 15.5,
        "selected": True,
        "tentative": False,
        "reason": "best latency",
    }
    result = format_backend_attempt_row(row)
    assert "kwin-dbus" in result
    assert "tested" in result
    assert "fresh-probe" in result
    assert "samples=10" in result
    assert "selected=yes" in result
    assert "tentative=no" in result


def test_format_backend_attempt_row_defaults() -> None:
    row = {}
    result = format_backend_attempt_row(row)
    assert "unknown" in result
    assert "skipped" in result
    assert "samples=0" in result


# ---------------------------------------------------------------------------
# _normalize_side_counts
# ---------------------------------------------------------------------------


def test_normalize_side_counts_valid() -> None:
    result = _normalize_side_counts((4, 3, 4, 3), source_zone_count=14)
    assert result == (4, 3, 4, 3)


def test_normalize_side_counts_wrong_length() -> None:
    result = _normalize_side_counts([1, 2, 3], source_zone_count=6)
    assert result is None


def test_normalize_side_counts_not_tuple_or_list() -> None:
    result = _normalize_side_counts("hello", source_zone_count=6)
    assert result is None


def test_normalize_side_counts_non_int_values() -> None:
    result = _normalize_side_counts(("a", "b", "c", "d"), source_zone_count=6)
    assert result is None


def test_normalize_side_counts_zero_sum() -> None:
    result = _normalize_side_counts((0, 0, 0, 0), source_zone_count=6)
    assert result is None


def test_normalize_side_counts_zero_sum_zero_source() -> None:
    result = _normalize_side_counts((0, 0, 0, 0), source_zone_count=0)
    assert result == (0, 0, 0, 0)


# ---------------------------------------------------------------------------
# _zone_side_for_index
# ---------------------------------------------------------------------------


def test_zone_side_for_index() -> None:
    # 4 top, 3 right, 4 bottom, 3 left = 14 total
    counts = (4, 3, 4, 3)
    assert _zone_side_for_index(0, counts) == "top"
    assert _zone_side_for_index(3, counts) == "top"
    assert _zone_side_for_index(4, counts) == "right"
    assert _zone_side_for_index(6, counts) == "right"
    assert _zone_side_for_index(7, counts) == "bottom"
    assert _zone_side_for_index(10, counts) == "bottom"
    assert _zone_side_for_index(11, counts) == "left"
    assert _zone_side_for_index(13, counts) == "left"
    assert _zone_side_for_index(99, counts) == "unknown"


# ---------------------------------------------------------------------------
# _png_pack
# ---------------------------------------------------------------------------


def test_png_pack() -> None:
    import zlib, struct
    data = b"hello"
    chunk = b"IEND" + data
    expected_crc = zlib.crc32(chunk) & 0xFFFFFFFF
    result = _png_pack(b"IEND", data)
    expected = struct.pack("!I", len(data)) + chunk + struct.pack("!I", expected_crc)
    assert result == expected


# ---------------------------------------------------------------------------
# _draw_rect
# ---------------------------------------------------------------------------


def test_draw_rect_basic() -> None:
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    _draw_rect(image, (10, 10, 30, 30), (255, 0, 0), thickness=2)
    # Check that some pixels were drawn in the border region
    assert np.any(image[10:12, 10:40, 0] == 255)  # top border
    assert np.any(image[38:40, 10:40, 0] == 255)  # bottom border


def test_draw_rect_out_of_bounds() -> None:
    """Rect entirely outside image should not crash."""
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    _draw_rect(image, (200, 200, 10, 10), (255, 0, 0))
    # No changes should be made
    assert np.all(image == 0)


# ---------------------------------------------------------------------------
# _synthetic_frame
# ---------------------------------------------------------------------------


def test_synthetic_frame() -> None:
    frame = _synthetic_frame(1920, 1080)
    assert frame.shape == (1080, 1920, 3)
    assert frame.dtype == np.uint8
    assert np.all(frame >= 40)


# ---------------------------------------------------------------------------
# evaluate_geometry
# ---------------------------------------------------------------------------


def test_evaluate_geometry_physical_match() -> None:
    status = {
        "kde_display_width": 3840,
        "kde_display_height": 2160,
        "kde_scale_factor": 1.0,
        "captured_frame_width": 3840,
        "captured_frame_height": 2160,
        "capture_width": 3840,
        "capture_height": 2160,
        "source_zone_count": 14,
        "source_zone_side_counts": (4, 3, 4, 3),
    }
    cfg = AppConfig()
    result = evaluate_geometry(status=status, cfg=cfg)
    assert result["matches_physical"] is True
    assert result["coordinate_mode"] == "physical"


def test_evaluate_geometry_scaled_match() -> None:
    status = {
        "kde_display_width": 3840,
        "kde_display_height": 2160,
        "kde_scale_factor": 2.0,
        "captured_frame_width": 1920,
        "captured_frame_height": 1080,
        "capture_width": 1920,
        "capture_height": 1080,
        "source_zone_count": 14,
    }
    cfg = AppConfig()
    result = evaluate_geometry(status=status, cfg=cfg)
    assert result["matches_logical"] is True
    assert result["coordinate_mode"] == "logical"


def test_evaluate_geometry_mismatch() -> None:
    status = {
        "kde_display_width": 3840,
        "kde_display_height": 2160,
        "kde_scale_factor": 1.0,
        "captured_frame_width": 1280,
        "captured_frame_height": 720,
        "capture_width": 3840,
        "capture_height": 2160,
        "source_zone_count": 14,
    }
    cfg = AppConfig()
    result = evaluate_geometry(status=status, cfg=cfg)
    assert result["geometry_warning"] is True


def test_evaluate_geometry_no_kde_data() -> None:
    status = {}
    cfg = AppConfig()
    result = evaluate_geometry(status=status, cfg=cfg)
    assert result["matches_physical"] is False
    assert result["capture_backend"] == "unknown"


# ---------------------------------------------------------------------------
# diagnostics_text_lines
# ---------------------------------------------------------------------------


def test_diagnostics_text_lines_basic() -> None:
    status = {
        "kde_display_width": 1920,
        "kde_display_height": 1080,
        "kde_scale_factor": 1.0,
        "captured_frame_width": 1920,
        "captured_frame_height": 1080,
        "capture_width": 1920,
        "capture_height": 1080,
        "source_zone_count": 14,
        "source_zone_side_counts": (4, 3, 4, 3),
        "effective_capture_backend": "mock",
        "edge_sampling_thickness": 8,
        "light_spread": "balanced",
        "display_preset": "sdr",
        "edge_locality": "balanced",
    }
    cfg = AppConfig(display_preset="sdr")
    lines = diagnostics_text_lines(status=status, cfg=cfg)
    assert len(lines) > 5
    assert any("KDE display resolution" in line for line in lines)
    assert any("Source-zone count" in line for line in lines)


def test_diagnostics_text_lines_with_geometry_warning() -> None:
    status = {
        "kde_display_width": 3840,
        "kde_display_height": 2160,
        "kde_scale_factor": 1.0,
        "captured_frame_width": 1280,
        "captured_frame_height": 720,
        "capture_width": 3840,
        "capture_height": 2160,
        "source_zone_count": 14,
        "source_zone_side_counts": (4, 3, 4, 3),
        "display_preset": "hdr",
    }
    cfg = AppConfig(display_preset="hdr")
    lines = diagnostics_text_lines(status=status, cfg=cfg)
    assert any("scaled" in line.lower() or "does not match" in line.lower() for line in lines)


# ---------------------------------------------------------------------------
# latency_breakdown_lines
# ---------------------------------------------------------------------------


def test_latency_breakdown_lines_no_measurement() -> None:
    status = {}
    lines = latency_breakdown_lines(status=status)
    assert any("Start mirroring" in line for line in lines)


def test_latency_breakdown_lines_no_stages() -> None:
    status = {"latency_measurement": {"live_mirroring_only": True}}
    lines = latency_breakdown_lines(status=status)
    assert any("unavailable" in line for line in lines)


def test_latency_breakdown_lines_with_stages() -> None:
    status = {
        "latency_measurement": {
            "live_mirroring_only": True,
            "target_fps": 60.0,
            "effective_output_fps": 58.0,
            "fps_cap": 0.0,
            "fps_cap_reason": "none",
            "dropped_or_skipped_frames": 2,
            "counters": {"no_pending_frame_ticks": 5, "capture_worker_error_count": 0},
            "flags": {"capture_worker_active": True},
            "labels": {
                "latest_capture_backend_name": "kwin-dbus",
                "hid_device_write_limited": "no",
            },
            "stages": {
                "actual_work_ms": {"available": True, "median_ms": 12.0, "p95_ms": 15.0, "sample_count": 100},
                "loop_gap_ms": {"available": True, "median_ms": 16.5, "p95_ms": 20.0, "sample_count": 100},
                "pacing_wait_ms": {"available": True, "median_ms": 0.5, "p95_ms": 1.0, "sample_count": 100},
                "frame_processing_ms": {"available": True, "median_ms": 8.0, "p95_ms": 10.0, "sample_count": 100},
                "hid_write_ms": {"available": True, "median_ms": 3.0, "p95_ms": 4.0, "sample_count": 100},
                "capture_wait_ms": {"available": True, "median_ms": 2.0, "p95_ms": 3.0, "sample_count": 100},
            },
        }
    }
    lines = latency_breakdown_lines(status=status)
    # Should contain timing info
    assert any("60.0" in line for line in lines)
    assert any("58.0" in line for line in lines)
    assert any("actual_work_ms" in line for line in lines)


def test_latency_breakdown_lines_with_fps_cap() -> None:
    status = {
        "latency_measurement": {
            "live_mirroring_only": True,
            "target_fps": 120.0,
            "effective_output_fps": 30.0,
            "fps_cap": 30.0,
            "fps_cap_reason": "auto-limited",
            "dropped_or_skipped_frames": 0,
            "counters": {},
            "flags": {},
            "labels": {},
            "stages": {
                "actual_work_ms": {"available": True, "median_ms": 5.0, "p95_ms": 7.0, "sample_count": 50},
                "loop_gap_ms": {"available": True, "median_ms": 33.0, "p95_ms": 35.0, "sample_count": 50},
                "pacing_wait_ms": {"available": True, "median_ms": 25.0, "p95_ms": 28.0, "sample_count": 50},
                "frame_processing_ms": {"available": True, "median_ms": 2.0, "p95_ms": 3.0, "sample_count": 50},
                "hid_write_ms": {"available": True, "median_ms": 2.0, "p95_ms": 3.0, "sample_count": 50},
                "capture_wait_ms": {"available": False, "sample_count": 0},
                "capture_call_ms": {"available": False, "sample_count": 0},
            },
        }
    }
    lines = latency_breakdown_lines(status=status)
    assert any("FPS cap" in line for line in lines)
    assert any("30.0" in line for line in lines)


# ---------------------------------------------------------------------------
# default_kde_display_metadata
# ---------------------------------------------------------------------------


def test_default_kde_display_metadata() -> None:
    result = default_kde_display_metadata()
    assert "kde_scale_factor" in result
    assert "kde_display_width" in result
    assert "kde_session_type" in result
