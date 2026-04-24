from __future__ import annotations

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.ui.calibration_state import (
    CalibrationState,
    backend_selection_info,
    build_latency_result,
    build_testing_panel_state,
    latency_result_summary,
    should_auto_run_latency_probe,
)


def test_shared_calibration_state_round_trips_core_fields() -> None:
    cfg = AppConfig(device_zone_count=0, zone_offset=3, reverse_zones=True, zone_preset="horizontal")
    state = CalibrationState.from_config(cfg, {"device_zone_count": 18})

    assert state.zone_preset == "horizontal"
    assert state.zone_offset == 3
    assert state.reverse_zones is True
    assert state.effective_device_zone_count() == 18


def test_calibration_state_uses_configured_device_zone_count_over_zone_rect_count() -> None:
    cfg = AppConfig(
        zones=[ZoneConfig(x=0.0, y=0.0, w=1.0, h=1.0)],
        device_zone_count=12,
    )
    state = CalibrationState.from_config(cfg, runtime_status={})
    assert state.zone_count == 1
    assert state.effective_device_zone_count() == 12


def test_corner_alignment_mode_reflects_live_offset_reverse() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=12, zone_offset=0, reverse_zones=False), {})
    base = state.step_for_mode("corner+offset alignment", 0)
    state.zone_offset = 2
    state.reverse_zones = True
    changed = state.step_for_mode("corner+offset alignment", 0)

    assert "offset=+0" in base.label
    assert "reverse=off" in base.label
    assert "offset=+2" in changed.label
    assert "reverse=on" in changed.label


def test_corner_anchored_model_changes_mapping_when_anchors_change() -> None:
    cfg = AppConfig(
        device_zone_count=12,
        calibration_model="corner_anchored",
        corner_anchor_top_left=0,
        corner_anchor_top_right=3,
        corner_anchor_bottom_right=6,
        corner_anchor_bottom_left=9,
    )
    state = CalibrationState.from_config(cfg, {})
    base = state.step_for_mode("direction walk", 0)
    state.corner_anchor_top_left = 1
    changed = state.step_for_mode("direction walk", 0)
    assert changed.device_zone_index != base.device_zone_index


def test_validation_report_only_requires_valid_unique_corner_anchors() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    fail = state.validation_report()
    assert fail.hard_fail is True

    state.corner_anchor_top_left = 0
    state.corner_anchor_top_right = 2
    state.corner_anchor_bottom_right = 4
    state.corner_anchor_bottom_left = 6
    passed = state.validation_report()

    assert passed.hard_fail is False
    assert passed.outcome_status == "pass"


def test_active_corner_offsets_are_inert_in_simplified_model() -> None:
    cfg = AppConfig(device_zone_count=8, corner_offsets_enabled=True, corner_zone_offsets=[99, -99, 30, -30])
    state = CalibrationState.from_config(cfg, {})
    assert state.active_corner_zone_offsets() == [0, 0, 0, 0]


def test_testing_step_controls_and_frame_generation_stay_coherent() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=6), {})
    mode = "direction walk"
    assert state.cycle_length(mode) == 6
    frame = state.frame_for_step(mode=mode, step=2, brightness=0.5, all_off_except_active=True)
    assert len(frame) == 6
    assert sum(1 for rgb in frame if rgb != (0, 0, 0)) == 1


def test_physical_walk_mode_steps_through_all_device_zones_in_order() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=48), {})
    walked = [state.step_for_mode("physical zone walk", step).device_zone_index for step in range(48)]
    assert walked == list(range(48))


def test_physical_walk_mode_ignores_offset_and_reverse_for_active_zone() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=48), {})
    base = [state.step_for_mode("physical zone walk", step).device_zone_index for step in (0, 1, 31, 47)]
    state.zone_offset = 17
    state.reverse_zones = True
    changed = [state.step_for_mode("physical zone walk", step).device_zone_index for step in (0, 1, 31, 47)]
    assert changed == base


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
    assert "[heuristic frame-interval estimate]" in summary
