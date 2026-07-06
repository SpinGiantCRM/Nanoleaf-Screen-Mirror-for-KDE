from __future__ import annotations

import pytest

from tests.qt_headless import load_headless_qt


def test_live_diagnostics_renders_runtime_status_and_zone_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qt, app = load_headless_qt(monkeypatch)
    from nanoleaf_sync.ui.live_diagnostics import LiveDiagnosticsDialog

    status = {
        "running": True,
        "runtime_warnings": [{"message": "capture lag"}],
        "latest_capture_source_identity": {
            "fingerprint": "screen-a",
            "confidence": "high",
            "scale_confidence": "exact",
        },
        "capture_source_change_count": 2,
        "capture_backend": "kwin-dbus",
        "capture_path": "screenshot2",
        "latest_frame_context": {
            "frame_seq": 42,
            "source": {"monitor_id": "DP-1"},
        },
        "captured_frame_width": 1920,
        "captured_frame_height": 1080,
        "latest_frame_mean_brightness": 12.4,
        "consecutive_black_frames": 1,
        "total_black_frames": 3,
        "hdr_colour_path": {
            "display_referred": True,
            "source": "backend metadata",
            "skip_display_gamut_adaptation": True,
            "sdr_boost_compensation_enabled": True,
            "portal_negotiated_format": "RGB",
        },
        "capture_colour_diagnostics": {
            "capture_source": {"metadata_source": "kwin"},
            "portal": {"pixel_format": "BGRx"},
            "kwin": {"screenshot2_method": "CaptureActiveScreen"},
        },
        "frames_sent": 99,
        "consecutive_errors": 0,
        "latency_measurement": {
            "target_fps": 60.0,
            "effective_output_fps": 58.5,
            "counters": {
                "capture_buffer_dropped_frames": 4,
                "process_buffer_dropped_frames": 5,
                "coalesced_sends": 6,
            },
        },
        "duplicate_output_skipped_frames": 7,
        "latest_staleness_ms": 8.5,
        "hid_live_send_policy": "latest-wins",
        "stale_output_drop_rate_per_second": 0.25,
        "sdr_boost_compensation_enabled": True,
        "lifecycle_state": "running",
        "configured_priority_mode": "high",
        "priority_apply_status": "applied",
        "priority_apply_error": "",
        "predictive_sync_active": True,
        "predictive_lookahead_frames": 1.5,
        "predictive_scene_cut_suppressed": True,
        "driver_ready": True,
        "capture_backend_ready": True,
        "calibration_status": "ready",
        "calibration_status_message": "Calibration is complete.",
        "last_error": "",
        "last_error_kind": "",
        "last_error_guidance": "",
        "startup_elapsed_ms": 123,
        "zone_diagnostics": [
            {
                "zone_index": 0,
                "side": "top",
                "selected_candidate": "edge",
                "sampled_rgb": (1, 2, 3),
                "final_output_rgb": (4, 5, 6),
            }
        ],
    }

    dialog = LiveDiagnosticsDialog(None, lambda: status, live_only=True)
    dialog.show()
    app.processEvents()

    assert dialog._last_refresh_ok is True
    assert dialog._timer.isActive()
    assert dialog._warnings_banner.isVisible()
    assert dialog._cap_labels["_cap_backend"].text() == "kwin-dbus"
    assert dialog._cap_labels["_cap_frame_seq"].text() == "42"
    assert dialog._cap_labels["_cap_source_monitor"].text() == "DP-1"
    assert dialog._cap_labels["_cap_frame_size"].text() == "1920\u00d71080"
    assert dialog._source_labels["_src_fingerprint"].text() == "screen-a"
    assert dialog._colour_labels["_colour_display_referred"].text() == "yes"
    assert dialog._colour_labels["_colour_metadata_source"].text() == "kwin"
    assert dialog._colour_labels["_colour_portal_format"].text() == "BGRx"
    assert dialog._colour_labels["_colour_kwin_method"].text() == "CaptureActiveScreen"
    assert dialog._pipe_labels["_pipe_target_fps"].text() == "60"
    assert dialog._pipe_labels["_pipe_eff_fps"].text() == "58.5"
    assert dialog._pipe_labels["_pipe_cap_drops"].text() == "4"
    assert dialog._pipe_labels["_pipe_hid_policy"].text() == "latest-wins"
    assert dialog._advanced_labels["_adv_pred_active"].text() == "yes"
    assert dialog._dev_labels["_dev_driver"].text() == "yes"
    assert dialog._err_labels["_err_last"].text() == "none"
    assert dialog._zone_grid is not None

    status["running"] = False
    dialog._do_refresh()
    assert not dialog._timer.isActive()


def test_live_diagnostics_refresh_failure_keeps_stale_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _qt, app = load_headless_qt(monkeypatch)
    from nanoleaf_sync.ui.live_diagnostics import LiveDiagnosticsDialog

    calls = {"count": 0}

    def _refresh() -> dict:
        calls["count"] += 1
        if calls["count"] > 1:
            raise RuntimeError("status unavailable")
        return {"running": False, "capture_backend": "kwin-dbus"}

    dialog = LiveDiagnosticsDialog(None, _refresh, live_only=False)
    dialog.show()
    app.processEvents()
    assert dialog._cap_labels["_cap_backend"].text() == "kwin-dbus"

    dialog._do_refresh()

    assert dialog._last_refresh_ok is False
    assert dialog._stale_banner.isVisible()
    assert "Refresh failed" in dialog._stale_banner.text()
    assert dialog._cap_labels["_cap_backend"].text() == "kwin-dbus"
