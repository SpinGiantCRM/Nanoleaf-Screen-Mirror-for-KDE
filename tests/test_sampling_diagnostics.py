from __future__ import annotations

from pathlib import Path

import numpy as np

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.diagnostics_exports import (
    diagnostics_text_lines,
    evaluate_geometry,
    export_latency_report,
    export_sampling_overlay,
    export_zone_report,
)
from nanoleaf_sync.runtime.state import RuntimeState
from nanoleaf_sync.capture.latency_probe import FrameTimingSample, STAGE_FRAME_TOTAL, STAGE_LOOP_GAP
from nanoleaf_sync.ui.calibration_state import LatencyProbeResult, latency_result_summary
from nanoleaf_sync.runtime.engine import process_frame
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones
from nanoleaf_sync.runtime.zones import zone_colors_array


def _make_4k_edge_frame() -> np.ndarray:
    frame = np.full((2160, 3840, 3), 128, dtype=np.uint8)
    t = 180
    frame[:t, :, :] = np.array([0, 255, 0], dtype=np.uint8)  # top green
    frame[:, 3840 - t :, :] = np.array([0, 0, 255], dtype=np.uint8)  # right blue
    frame[2160 - t :, :, :] = np.array([255, 255, 0], dtype=np.uint8)  # bottom yellow
    frame[:, :t, :] = np.array([255, 0, 0], dtype=np.uint8)  # left red
    return frame


def test_synthetic_side_colours_map_to_expected_edges() -> None:
    zones = make_edge_weighted_zones(20, width=3840, height=2160, edge_locality="tight")
    zones_px = zones_from_config(zones, 3840, 2160)
    colors = zone_colors_array(_make_4k_edge_frame(), zones_px, sample_step=1)
    assert np.mean(colors[:5, 1]) > np.mean(colors[:5, 2])  # top greener than blue
    assert np.mean(colors[5:10, 2]) > np.mean(colors[5:10, 0])  # right is blue dominant
    assert np.mean(colors[10:15, 0]) > 120 and np.mean(colors[10:15, 1]) > 120  # bottom yellow
    assert np.mean(colors[15:20, 0]) > np.mean(colors[15:20, 1])  # left red


def test_left_purple_remains_local_and_far_side_stays_neutral() -> None:
    frame = np.full((2160, 3840, 3), 120, dtype=np.uint8)
    frame[:, :500, :] = np.array([200, 0, 220], dtype=np.uint8)
    frame[:, 3300:3500, :] = np.array([0, 255, 0], dtype=np.uint8)
    zones_px = zones_from_config(make_edge_weighted_zones(20, width=3840, height=2160, edge_locality="tight"), 3840, 2160)
    colors = zone_colors_array(frame, zones_px, sample_step=1)
    left_mean_blue = float(np.mean(colors[15:20, 2]))
    right_mean_blue = float(np.mean(colors[5:10, 2]))
    assert left_mean_blue > right_mean_blue + 40
    assert float(np.mean(colors[5:10, 0])) < 170


def test_bottom_left_green_block_stays_local() -> None:
    frame = np.full((2160, 3840, 3), 110, dtype=np.uint8)
    frame[1700:2160, :500, :] = np.array([0, 255, 0], dtype=np.uint8)
    zones_px = zones_from_config(make_edge_weighted_zones(20, width=3840, height=2160, edge_locality="tight"), 3840, 2160)
    colors = zone_colors_array(frame, zones_px, sample_step=1)
    assert np.max(colors[10:20, 1]) > 150
    assert np.mean(colors[:5, 1]) < 140


def test_geometry_warning_for_fractional_scaling_mismatch() -> None:
    cfg = AppConfig()
    status = {
        "kde_display_width": 3840,
        "kde_display_height": 2160,
        "kde_scale_factor": 1.7,
        "captured_frame_width": 480,
        "captured_frame_height": 270,
        "capture_width": 480,
        "capture_height": 270,
    }
    geo = evaluate_geometry(status=status, cfg=cfg)
    assert geo["geometry_warning"] is True
    assert geo["coordinate_mode"] in {"scaled", "unknown"}


def test_diagnostics_text_includes_4k_and_170_percent_path() -> None:
    cfg = AppConfig()
    status = {
        "kde_display_width": 3840,
        "kde_display_height": 2160,
        "kde_scale_factor": 1.7,
        "captured_frame_width": 2260,
        "captured_frame_height": 1271,
    }
    lines = diagnostics_text_lines(status=status, cfg=cfg)
    text = "\n".join(lines)
    assert "3840x2160" in text
    assert "1.7" in text


def test_overlay_export_creates_png(tmp_path: Path) -> None:
    frame = _make_4k_edge_frame()
    zones_px = zones_from_config(make_edge_weighted_zones(12, width=3840, height=2160), 3840, 2160)
    out = export_sampling_overlay(
        frame=frame,
        zones=zones_px,
        side_counts=(3, 3, 3, 3),
        status={},
        cfg=AppConfig(),
    )
    assert out.exists()
    assert out.suffix == ".png"


def test_live_overlay_export_requires_real_frame() -> None:
    zones_px = zones_from_config(make_edge_weighted_zones(12, width=3840, height=2160), 3840, 2160)
    try:
        export_sampling_overlay(
            frame=None,
            zones=zones_px,
            side_counts=(3, 3, 3, 3),
            status={},
            cfg=AppConfig(),
        )
        assert False, "expected ValueError for missing live frame"
    except ValueError as exc:
        assert "No live frame available" in str(exc)


def test_synthetic_overlay_export_is_explicit() -> None:
    zones_px = zones_from_config(make_edge_weighted_zones(12, width=3840, height=2160), 3840, 2160)
    out = export_sampling_overlay(
        frame=None,
        zones=zones_px,
        side_counts=(3, 3, 3, 3),
        status={},
        cfg=AppConfig(),
        synthetic=True,
    )
    assert "synthetic-test" in out.name


def test_empty_zone_report_is_rejected() -> None:
    try:
        export_zone_report(rows=[])
        assert False, "expected ValueError for empty diagnostics"
    except ValueError as exc:
        assert "No per-zone diagnostics available" in str(exc)


def test_latency_summary_does_not_fabricate_idle_value() -> None:
    assert "Live latency: Not measured" in latency_result_summary(None)
    result = LatencyProbeResult(
        requested_policy="auto",
        selected_backend="not-started",
        selection_source="manual-policy",
        selection_reason="Runtime not started",
        measured_latency_ms=0.0,
        measurement_kind="unavailable",
        confidence_note="Runtime has not processed frames yet.",
        triggered_by="manual",
        recorded_at_utc="2026-04-24T00:00:00+00:00",
        details="Configured frame interval: 8.3 ms at 120 FPS",
    )
    text = latency_result_summary(result)
    assert "Live latency: Not measured" in text
    assert "Configured frame interval: 8.3 ms at 120 FPS" in text


def test_per_zone_differences_survive_processing() -> None:
    frame = _make_4k_edge_frame()
    zones_px = zones_from_config(make_edge_weighted_zones(20, width=3840, height=2160, edge_locality="tight"), 3840, 2160)
    idx = np.arange(len(zones_px), dtype=np.intp)
    out = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=idx,
        brightness=1.0,
        smoothing=1.0,
        motion_preset="responsive",
        color_style="reference",
        edge_locality="tight",
    )
    out_arr = np.asarray(out)
    assert out_arr.shape[0] == len(zones_px)
    assert np.std(out_arr[:, 0]) > 10
    assert np.std(out_arr[:, 1]) > 10


def test_latency_diagnostics_show_unavailable_stage_honestly() -> None:
    state = RuntimeState()
    state.latency_probe.add_stage_sample(
        FrameTimingSample(stage_ms={STAGE_FRAME_TOTAL: 8.0, STAGE_LOOP_GAP: 10.0})
    )
    status = state.status_snapshot(
        running=True,
        capture_backend_name="kmsgrab",
        capture_path=None,
        capture_width=1920,
        capture_height=1080,
        max_consecutive_errors=5,
        reinit_backoff_ms=500,
    )
    lines = diagnostics_text_lines(status=status, cfg=AppConfig())
    text = "\n".join(lines)
    assert "capture_read_ms: unavailable" in text
    assert "frame_total_ms: median=" in text


def test_latency_samples_reset_on_runtime_start() -> None:
    state = RuntimeState()
    state.latency_probe.add_stage_sample(
        FrameTimingSample(stage_ms={STAGE_FRAME_TOTAL: 7.0, STAGE_LOOP_GAP: 8.0})
    )
    assert state.latency_probe.measurement() is not None
    state.reset_for_start()
    assert state.latency_probe.measurement() is None


def test_latency_export_includes_new_stage_fields() -> None:
    state = RuntimeState()
    state.latency_probe.add_stage_sample(
        FrameTimingSample(stage_ms={STAGE_FRAME_TOTAL: 9.0, STAGE_LOOP_GAP: 12.0})
    )
    status = state.status_snapshot(
        running=True,
        capture_backend_name="kmsgrab",
        capture_path=None,
        capture_width=1920,
        capture_height=1080,
        max_consecutive_errors=5,
        reinit_backoff_ms=500,
    )
    out = export_latency_report(status=status)
    payload = out.read_text(encoding="utf-8")
    assert "stage,available,sample_count,median_ms,p95_ms,max_ms" in payload
    assert "frame_total_ms,True,1,9.0,9.0,9.0" in payload
