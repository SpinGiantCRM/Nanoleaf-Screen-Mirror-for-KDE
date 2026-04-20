from __future__ import annotations

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.calibration_state import (
    CalibrationState,
    backend_selection_info,
    build_latency_result,
    latency_result_summary,
    next_corner_start_anchor,
    should_auto_run_latency_probe,
    build_testing_panel_state,
)


def test_shared_calibration_state_round_trips_core_fields() -> None:
    cfg = AppConfig(device_zone_count=0, zone_offset=3, reverse_zones=True, zone_preset="horizontal")
    state = CalibrationState.from_config(cfg, {"device_zone_count": 18})

    assert state.zone_preset == "horizontal"
    assert state.zone_offset == 3
    assert state.reverse_zones is True
    assert state.auto_device_zone_count is True
    assert state.effective_device_zone_count() == 18


def test_combined_corner_offset_mode_reflects_live_offset_reverse() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=12, zone_offset=0, reverse_zones=False), {})
    base = state.step_for_mode("corner+offset alignment", 0)
    state.zone_offset = 2
    state.reverse_zones = True
    changed = state.step_for_mode("corner+offset alignment", 0)

    assert "offset=+0" in base.label
    assert "reverse=off" in base.label
    assert "offset=+2" in changed.label
    assert "reverse=on" in changed.label


def test_manual_corner_anchor_assignment_guides_corner_steps() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    state.corner_start_anchor = 5
    step = state.step_for_mode("corner+offset alignment", 0)
    assert "#6" in step.label
    assert next_corner_start_anchor(5, device_zone_count=8) == 6


def test_latency_policy_is_predictable_and_manual_vs_auto_labeled() -> None:
    assert should_auto_run_latency_probe(policy="manual", last_result=None, active_backend="kwin-dbus") is False
    assert should_auto_run_latency_probe(policy="on-open", last_result=None, active_backend="kwin-dbus") is True

    result = build_latency_result(
        requested_policy="auto",
        selected_backend="kwin-dbus",
        selection_source="auto-probe",
        selection_reason="probe winner",
        measured_latency_ms=23.4,
        measurement_kind="estimated",
        confidence_note="fps-derived",
        triggered_by="manual",
    )
    assert should_auto_run_latency_probe(
        policy="on-open-once-per-backend",
        last_result=result,
        active_backend="kwin-dbus",
    ) is False
    assert should_auto_run_latency_probe(
        policy="on-open-once-per-backend",
        last_result=result,
        active_backend="kmsgrab",
    ) is True
    summary = latency_result_summary(result)
    assert "backend=kwin-dbus" in summary
    assert "measurement_kind" not in summary
    assert "[estimated]" in summary


def test_testing_step_controls_and_frame_generation_stay_coherent() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=6), {})
    mode = "direction walk"
    assert state.cycle_length(mode) == 6
    frame = state.frame_for_step(mode=mode, step=2, brightness=0.5, all_off_except_active=True)
    assert len(frame) == 6
    assert sum(1 for rgb in frame if rgb != (0, 0, 0)) == 1


def test_manual_device_zone_count_48_propagates_to_cycle_frame_and_preview() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=48, zone_offset=1), {})
    assert state.auto_device_zone_count is False
    assert state.effective_device_zone_count() == 48
    assert state.cycle_length("direction walk") == 48

    frame = state.frame_for_step(mode="direction walk", step=11, brightness=1.0, all_off_except_active=True)
    assert len(frame) == 48
    preview = state.mapping_preview_text()
    assert "configured strip zone count 48" in preview


def test_auto_device_zone_detection_failure_is_explicit() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=0), {"device_zone_count": 0})
    assert state.auto_device_zone_count is True
    assert "Auto detection failed" in state.auto_detection_status()
    assert "fallback source zone count" in state.auto_detection_status()


def test_backend_and_testing_state_are_exposed_for_ui_surfaces() -> None:
    cfg = AppConfig(prefer_backend="auto")
    runtime_status = {
        "requested_capture_backend": "auto",
        "effective_capture_backend": "kwin-dbus",
        "selection_reason": "probe winner",
        "from_auto_probe": True,
    }
    state = CalibrationState.from_config(AppConfig(device_zone_count=48), runtime_status)
    backend = backend_selection_info(runtime_status, cfg)
    assert backend.selected_backend == "kwin-dbus"
    assert backend.source == "auto-probe"
    panel = build_testing_panel_state(state=state, runtime_status=runtime_status, cfg=cfg, mode="direction walk", step=0)
    assert "Effective runtime backend: kwin-dbus" in panel.backend_summary
    assert panel.effective_zone_count == 48
    assert "Device zone mode:" in panel.zone_mode_summary


def test_corner_refinement_preview_mentions_corner_offsets() -> None:
    cfg = AppConfig(device_zone_count=8, corner_offsets_enabled=True, corner_zone_offsets=[1, -1, 2, -2])
    state = CalibrationState.from_config(cfg, {})
    text = state.mapping_preview_text()
    assert "Per-corner refinement" in text
    assert "+1/-1/+2/-2" in text


def test_corner_refinement_clamps_to_supported_limit() -> None:
    cfg = AppConfig(device_zone_count=8, corner_offsets_enabled=True, corner_zone_offsets=[99, -99, 30, -30])
    state = CalibrationState.from_config(cfg, {})
    assert state.active_corner_zone_offsets() == [24, -24, 24, -24]


def test_backend_selection_never_reports_auto_as_selected_backend() -> None:
    cfg = AppConfig(prefer_backend="auto")
    info = backend_selection_info({"requested_capture_backend": "auto", "running": True}, cfg)
    assert info.selected_backend == "unresolved"
    assert info.effective_backend == "unresolved"
    assert "No concrete backend implementation resolved" in info.unresolved_reason


def test_backend_selection_marks_not_started_state_explicitly() -> None:
    cfg = AppConfig(prefer_backend="auto")
    info = backend_selection_info({}, cfg)
    assert info.effective_backend == "not-started"
    assert info.runtime_started is False
    assert "not started" in info.unresolved_reason
