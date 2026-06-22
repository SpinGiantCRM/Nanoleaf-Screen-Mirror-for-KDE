import threading
import time

import numpy as np

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.runtime.engine import (
    _ensure_runtime_artifacts,
    _estimate_processing_staleness_ms,
    _mapping_signature,
    process_frame,
    run_loop,
)
from nanoleaf_sync.runtime.state import RuntimeState
from nanoleaf_sync.ui.zone_presets import edge_side_counts


def _cfg_with_valid_calibration(zone_count: int = 48, **kwargs) -> AppConfig:
    calibration = CalibrationConfig(
        device_zone_count=zone_count,
        corner_anchor_top_left=0,
        corner_anchor_top_right=zone_count // 4,
        corner_anchor_bottom_right=zone_count // 2,
        corner_anchor_bottom_left=(3 * zone_count) // 4,
        reverse_zones=bool(kwargs.pop("reverse_zones", False)),
    )
    return AppConfig(device_zone_count=zone_count, calibration=calibration, **kwargs)


def test_mapping_signature_tracks_reverse_and_model() -> None:
    cfg = _cfg_with_valid_calibration(10, calibration_model="corner_anchored", reverse_zones=True)
    sig = _mapping_signature(source_zone_count=10, config=cfg, detected_device_zone_count=10)
    assert sig[0] == 10
    assert isinstance(sig[3], bool)


def test_processing_staleness_estimate_includes_frame_age_and_expected_output_work() -> None:
    estimate = _estimate_processing_staleness_ms(
        captured_at=10.0,
        now=10.012,
        hid_output_work_ewma_ms=6.5,
    )
    assert 18.4 <= estimate <= 18.6


def test_processing_staleness_estimate_clamps_clock_reversal() -> None:
    estimate = _estimate_processing_staleness_ms(
        captured_at=10.1,
        now=10.0,
        hid_output_work_ewma_ms=None,
    )
    assert estimate == 0.0


def test_no_global_zone_offset_reintroduced() -> None:
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[:, :] = [12, 12, 12]
    frame[:6, :, :] = [255, 0, 0]
    cfg = _cfg_with_valid_calibration(48, zones=[], layout_preset="edge_strip")
    state = RuntimeState()
    zones_px, device_zone_indices = _ensure_runtime_artifacts(
        state=state, config=cfg, img_w=160, img_h=90, detected_device_zone_count=48
    )
    colors = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=device_zone_indices,
        brightness=1.0,
        smoothing=1.0,
    )
    top, right, bottom, _left = edge_side_counts(zone_count=48, width=160, height=90)
    assert sum(1 for c in colors[:top] if c[0] > 120) >= max(1, top - 2)
    assert sum(1 for c in colors[top + right : top + right + bottom] if c[0] > 90) <= 1


def test_tight_locality_keeps_bottom_left_signal_local() -> None:
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[-8:, :8, :] = [0, 255, 0]

    cfg = _cfg_with_valid_calibration(
        48, zones=[], layout_preset="edge_strip", edge_locality="tight"
    )
    state = RuntimeState()
    zones_px, device_zone_indices = _ensure_runtime_artifacts(
        state=state, config=cfg, img_w=160, img_h=90, detected_device_zone_count=48
    )
    colors = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=device_zone_indices,
        brightness=1.0,
        smoothing=1.0,
        edge_locality="tight",
    )

    top_n, right_n, bottom_n, left_n = edge_side_counts(zone_count=48, width=160, height=90)
    bottom = colors[top_n + right_n : top_n + right_n + bottom_n]
    colors[top_n + right_n + bottom_n : top_n + right_n + bottom_n + left_n]

    assert sum(1 for c in bottom[-4:] if c[1] > 85) >= 1
    assert sum(1 for c in bottom[:4] if c[1] > 60) == 0


def test_wide_locality_is_broader_than_tight_but_not_global() -> None:
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[-8:, :8, :] = [0, 255, 0]
    cfg = _cfg_with_valid_calibration(48, zones=[], layout_preset="edge_strip")
    state = RuntimeState()
    zones_px, device_zone_indices = _ensure_runtime_artifacts(
        state=state, config=cfg, img_w=160, img_h=90, detected_device_zone_count=48
    )

    tight = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=device_zone_indices,
        brightness=1.0,
        smoothing=1.0,
        edge_locality="tight",
    )
    wide = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=device_zone_indices,
        brightness=1.0,
        smoothing=1.0,
        edge_locality="wide",
    )

    top_n, right_n, bottom_n, _left_n = edge_side_counts(zone_count=48, width=160, height=90)
    tight_bottom = tight[top_n + right_n : top_n + right_n + bottom_n]
    wide_bottom = wide[top_n + right_n : top_n + right_n + bottom_n]

    tight_active = sum(1 for c in tight_bottom if c[1] > 60)
    wide_active = sum(1 for c in wide_bottom if c[1] > 60)
    assert wide_active >= tight_active
    assert wide_active < len(wide_bottom)


def test_sampling_quality_does_not_change_layout_geometry() -> None:
    cfg = _cfg_with_valid_calibration(48, zones=[], layout_preset="edge_strip")
    state = RuntimeState()
    zones_px_a, _ = _ensure_runtime_artifacts(
        state=state, config=cfg, img_w=160, img_h=90, detected_device_zone_count=48
    )
    cfg2 = _cfg_with_valid_calibration(
        48, zones=[], layout_preset="edge_strip", sampling_quality="low"
    )
    state2 = RuntimeState()
    zones_px_b, _ = _ensure_runtime_artifacts(
        state=state2, config=cfg2, img_w=160, img_h=90, detected_device_zone_count=48
    )
    assert zones_px_a == zones_px_b


def test_motion_preset_does_not_break_spatial_locality() -> None:
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[:8, -8:, :] = [255, 0, 0]
    cfg = _cfg_with_valid_calibration(
        48, zones=[], layout_preset="edge_strip", motion_preset="dynamic"
    )
    state = RuntimeState()
    zones_px, device_zone_indices = _ensure_runtime_artifacts(
        state=state, config=cfg, img_w=160, img_h=90, detected_device_zone_count=48
    )
    colors = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=device_zone_indices,
        brightness=1.0,
        smoothing=1.0,
        motion_preset="dynamic",
    )
    top_n, right_n, bottom_n, _left_n = edge_side_counts(zone_count=48, width=160, height=90)
    top = colors[:top_n]
    bottom = colors[top_n + right_n : top_n + right_n + bottom_n]
    assert sum(1 for c in top[-4:] if c[0] > 85) >= 1
    assert sum(1 for c in bottom if c[0] > 70) <= 1


def test_process_frame_reports_zone_sampling_timing_after_optimisation() -> None:
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    frame[:8, -8:, :] = [255, 0, 0]
    cfg = _cfg_with_valid_calibration(48, zones=[], layout_preset="edge_strip")
    state = RuntimeState()
    zones_px, device_zone_indices = _ensure_runtime_artifacts(
        state=state,
        config=cfg,
        img_w=160,
        img_h=90,
        detected_device_zone_count=48,
    )
    _out, _sampled, _pre, _final, timings, _smooth, _history = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=device_zone_indices,
        brightness=1.0,
        smoothing=1.0,
        return_diagnostics=True,
    )
    assert timings.zone_sampling_ms is not None
    assert timings.zone_sampling_ms >= 0.0


def test_run_loop_waits_when_no_pending_frame_available() -> None:
    class _NoFrameCapture:
        name = "kwin-dbus"
        last_capture_path = "kwin-dbus:test"

        def capture(self):
            return None

    class _DummyDriver:
        def send_frame(self, _colors):
            return None

    state = RuntimeState()
    cfg = _cfg_with_valid_calibration(48, fps=120)
    stopper = threading.Thread(
        target=lambda: (time.sleep(0.06), state.stop_event.set()), daemon=True
    )
    stopper.start()
    run_loop(
        config=cfg,
        state=state,
        get_capture=lambda: _NoFrameCapture(),
        get_driver=lambda: _DummyDriver(),
        install_drivers=lambda: True,
        close_backends=lambda: None,
    )
    measurement = state.latency_probe.measurement()
    assert measurement is not None
    no_pending = int(measurement.counters.get("no_pending_frame_ticks", 0))
    assert no_pending < 40
    assert "no_pending_frame_rate_per_second" in measurement.labels
    assert measurement.stages["runtime_idle_wait_ms"].available
    assert measurement.stages["frame_available_wait_ms"].available
    assert measurement.stages["runtime_capture_call_ms"].available


def test_run_loop_records_live_send_policy_without_response_wait_penalty() -> None:
    class _FastCapture:
        name = "kwin-dbus"
        last_capture_path = "kwin-dbus:test"

        def capture(self):
            frame = np.zeros((24, 32, 3), dtype=np.uint8)
            frame[:, :] = [30, 40, 50]
            return frame

    class _FastDriver:
        reported_zone_count = 48
        zone_count = 48

        def send_frame_with_timing(self, _colors):
            return {
                "frame_build_ms": 0.30,
                "device_write_ms": 1.20,
                "flush_or_wait_ms": 0.10,
                "device_limited": False,
                "flush_or_wait_reason": "Bounded nonblocking drain for stale responses.",
                "reports_per_frame": 3,
                "bytes_per_report": 64,
                "total_frame_bytes": 147,
                "report_data_sizes": [64, 64, 19],
                "per_report_write_ms": [0.4, 0.4, 0.4],
                "write_blocking": True,
                "write_retry_policy": "none",
                "write_rate_limit_policy": "none",
                "write_read_calls": 0,
                "live_send_policy": "nonblocking_drain",
                "response_wait_skipped": True,
            }

    state = RuntimeState()
    cfg = _cfg_with_valid_calibration(48, fps=60)

    def _stop_after_first_send_or_timeout() -> None:
        deadline = time.perf_counter() + 0.5
        while time.perf_counter() < deadline and not state.first_frame_sent:
            time.sleep(0.005)
        state.stop_event.set()

    stopper = threading.Thread(
        target=_stop_after_first_send_or_timeout,
        daemon=True,
    )
    stopper.start()
    run_loop(
        config=cfg,
        state=state,
        get_capture=lambda: _FastCapture(),
        get_driver=lambda: _FastDriver(),
        install_drivers=lambda: True,
        close_backends=lambda: None,
    )
    measurement = state.latency_probe.measurement()
    assert measurement is not None
    assert measurement.labels.get("hid_live_send_policy") == "nonblocking_drain"
    assert measurement.labels.get("hid_response_wait_skipped") == "yes"
    assert measurement.labels.get("hid_write_read_calls") == "0"
    assert measurement.stages["hid_flush_or_wait_ms"].available
    assert float(measurement.stages["hid_flush_or_wait_ms"].median_ms) < 5.0


def test_run_loop_fails_start_when_no_first_frame_arrives() -> None:
    class _NoFrameCapture:
        name = "kwin-dbus"
        last_capture_path = "unavailable"

        def capture(self):
            return None

    class _Driver:
        reported_zone_count = 48
        zone_count = 48

        def send_frame(self, _colors):
            return None

    state = RuntimeState()
    cfg = _cfg_with_valid_calibration(48, fps=60)
    cfg.startup_frame_timeout_s = 0.12
    run_loop(
        config=cfg,
        state=state,
        get_capture=lambda: _NoFrameCapture(),
        get_driver=lambda: _Driver(),
        install_drivers=lambda: True,
        close_backends=lambda: None,
    )

    assert state.startup_complete.is_set()
    assert state.startup_succeeded is False
    assert state.first_frame_seen is False
    assert state.first_frame_processed is False
    assert state.first_frame_sent is False
    assert state.startup_elapsed_ms > 0.0
    assert state.start_failure_reason.startswith("Start failed before first frame")


def test_run_loop_marks_startup_complete_after_first_frame_send() -> None:
    class _Capture:
        name = "kwin-dbus"
        last_capture_path = "kwin-dbus:test"

        def capture(self):
            frame = np.zeros((24, 32, 3), dtype=np.uint8)
            frame[:, :] = [80, 20, 10]
            return frame

    class _Driver:
        reported_zone_count = 48
        zone_count = 48

        def send_frame(self, _colors):
            state.stop_event.set()

    state = RuntimeState()
    cfg = _cfg_with_valid_calibration(48, fps=30)
    run_loop(
        config=cfg,
        state=state,
        get_capture=lambda: _Capture(),
        get_driver=lambda: _Driver(),
        install_drivers=lambda: True,
        close_backends=lambda: None,
    )

    assert state.startup_complete.is_set()
    assert state.first_frame_seen is True
    assert state.first_frame_processed is True
    assert state.first_frame_sent is True
    assert state.startup_succeeded is True
    assert state.first_frame_sent is True


def test_runtime_status_reports_calibration_incomplete_for_missing_anchors() -> None:
    cfg = AppConfig(
        device_zone_count=48,
        calibration=CalibrationConfig(device_zone_count=48),
        zones=[],
        layout_preset="edge_strip",
    )
    state = RuntimeState()
    zones_px, device_zone_indices = _ensure_runtime_artifacts(
        state=state,
        config=cfg,
        img_w=160,
        img_h=90,
        detected_device_zone_count=48,
    )

    assert zones_px
    assert device_zone_indices.size == 0
    status = state.status_snapshot(
        running=True,
        capture_backend_name="kwin-dbus",
        capture_path="kwin-dbus:test",
        capture_width=160,
        capture_height=90,
        max_consecutive_errors=5,
        reinit_backoff_ms=500,
    )
    assert status["calibration_status"] == "calibration_incomplete"
    assert status["last_error_kind"] == "calibration_incomplete"
    assert "calibration_incomplete" in status["calibration_status_message"]


def test_run_loop_does_not_stream_when_calibration_incomplete() -> None:
    class _Capture:
        name = "kwin-dbus"
        last_capture_path = "kwin-dbus:test"

        def capture(self):
            frame = np.zeros((24, 32, 3), dtype=np.uint8)
            frame[:, :] = [80, 20, 10]
            return frame

    class _Driver:
        reported_zone_count = 48
        zone_count = 48

        def __init__(self) -> None:
            self.sent_frames = []

        def send_frame(self, colors):
            self.sent_frames.append(colors)
            state.stop_event.set()

    state = RuntimeState()
    driver = _Driver()
    cfg = AppConfig(
        device_zone_count=48,
        calibration=CalibrationConfig(device_zone_count=48),
        zones=[],
        layout_preset="edge_strip",
        fps=30,
    )
    run_loop(
        config=cfg,
        state=state,
        get_capture=lambda: _Capture(),
        get_driver=lambda: driver,
        install_drivers=lambda: True,
        close_backends=lambda: None,
    )

    assert driver.sent_frames == []
    assert state.frames_sent == 0
    assert state.first_frame_seen is True
    assert state.first_frame_processed is False
    assert state.first_frame_sent is False
    assert state.startup_complete.is_set()
    assert state.startup_succeeded is False
    assert state.lifecycle_state == "calibration_incomplete"
    assert state.last_error_kind == "calibration_incomplete"
    assert "calibration_incomplete" in state.start_failure_reason


def test_run_loop_pipeline_records_process_buffer_drops_when_hid_is_slow() -> None:
    class _Capture:
        name = "kwin-dbus"
        last_capture_path = "kwin-dbus:test"

        def __init__(self) -> None:
            self._frames = 0

        def capture(self):
            self._frames += 1
            frame = np.zeros((24, 32, 3), dtype=np.uint8)
            frame[:, :] = [80, 20, 10]
            if self._frames >= 40:
                state.stop_event.set()
            return frame

    class _Driver:
        reported_zone_count = 48
        zone_count = 48

        def send_frame(self, _colors) -> None:
            time.sleep(0.025)

    state = RuntimeState()
    capture = _Capture()
    cfg = _cfg_with_valid_calibration(48, fps=60)
    thread = threading.Thread(
        target=run_loop,
        kwargs={
            "config": cfg,
            "state": state,
            "get_capture": lambda: capture,
            "get_driver": lambda: _Driver(),
            "install_drivers": lambda: True,
            "close_backends": lambda: None,
        },
        daemon=True,
    )
    thread.start()
    thread.join(timeout=8.0)
    assert not thread.is_alive()

    measurement = state.latency_probe.measurement()
    assert measurement is not None
    counters = measurement.counters
    dropped_total = int(counters.get("process_buffer_dropped_frames", 0)) + int(
        counters.get("capture_buffer_dropped_frames", 0)
    )
    assert dropped_total >= 1
