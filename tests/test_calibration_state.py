from __future__ import annotations

import logging

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.ui.calibration_flow import CalibrationPhaseDefinition
from nanoleaf_sync.ui.calibration_state import (
    MIN_CALIBRATION_VALIDATION_CONFIDENCE,
    CalibrationState,
    ZONE_COUNT_DIRECTLY_AFFECTED_PHASES,
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
    assert state.effective_device_zone_count() == 18


def test_calibration_state_does_not_derive_device_zone_count_from_zone_rect_count() -> None:
    cfg = AppConfig(
        zones=[ZoneConfig(x=0.0, y=0.0, w=1.0, h=1.0)],
        device_zone_count=12,
    )
    state = CalibrationState.from_config(cfg, runtime_status={})
    assert state.zone_count == 1
    assert state.effective_device_zone_count() == 12
    assert state.cycle_length("corner+offset alignment") == 4


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


def test_manual_mapping_uses_explicit_config_flag_not_map_presence() -> None:
    disabled = CalibrationState.from_config(
        AppConfig(device_zone_count=4, manual_mapping_enabled=False, explicit_zone_map=[0, 0, 0, 0]),
        {},
    )
    enabled = CalibrationState.from_config(
        AppConfig(device_zone_count=4, manual_mapping_enabled=True, explicit_zone_map=[0, 0, 0, 0]),
        {},
    )

    assert disabled.manual_mapping_enabled is False
    assert enabled.manual_mapping_enabled is True


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
    assert changed.source_zone_index != base.source_zone_index


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
    assert "[heuristic frame-interval estimate]" in summary


def test_latency_summary_distinguishes_measured_vs_estimated() -> None:
    measured = build_latency_result(
        requested_policy="auto",
        selected_backend="kwin-dbus",
        selection_source="auto-probe",
        selection_reason="probe winner",
        measured_latency_ms=21.0,
        measurement_kind="measured",
        confidence_note="runtime samples",
        triggered_by="manual",
    )
    estimated = build_latency_result(
        requested_policy="auto",
        selected_backend="kwin-dbus",
        selection_source="auto-probe",
        selection_reason="probe winner",
        measured_latency_ms=16.7,
        measurement_kind="estimated",
        confidence_note="fps-derived",
        triggered_by="manual",
    )
    assert "[measured pipeline latency]" in latency_result_summary(measured)
    assert "[heuristic frame-interval estimate]" in latency_result_summary(estimated)


def test_testing_step_controls_and_frame_generation_stay_coherent() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=6), {})
    mode = "direction walk"
    assert state.cycle_length(mode) == 6
    frame = state.frame_for_step(mode=mode, step=2, brightness=0.5, all_off_except_active=True)
    assert len(frame) == 6
    assert sum(1 for rgb in frame if rgb != (0, 0, 0)) == 1


def test_corner_alignment_zone_offset_and_test_zone_step_are_independent() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8, zone_offset=5), {})
    cycle = state.cycle_length("corner+offset alignment")
    first = state.step_for_mode("corner+offset alignment", 0)
    wrapped = state.step_for_mode("corner+offset alignment", cycle)

    assert state.zone_offset == 5
    assert first.device_zone_index == wrapped.device_zone_index
    assert "mapping zone offset=+5" in first.label
    assert "test zone step 1/" in first.label


def test_manual_device_zone_count_48_propagates_to_cycle_frame_and_preview() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=48, zone_offset=1), {})
    assert state.effective_device_zone_count() == 48
    assert state.cycle_length("direction walk") == 48

    frame = state.frame_for_step(mode="direction walk", step=11, brightness=1.0, all_off_except_active=True)
    assert len(frame) == 48
    preview = state.mapping_preview_text()
    assert "Using configured strip zone count 48" in preview


def test_configured_device_zone_mode_no_longer_reports_auto_detection() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=0), {"device_zone_count": 0})
    assert "Using configured strip zone count" in state.auto_detection_status()


def test_detected_device_zone_mode_reports_auto_detection() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=0), {"device_zone_count": 12})
    assert "Using auto-detected strip zone count 12" in state.auto_detection_status()


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
    assert "Strip LED zone mode:" in panel.zone_mode_summary


def test_corner_refinement_preview_mentions_corner_offsets() -> None:
    cfg = AppConfig(device_zone_count=8, corner_offsets_enabled=True, corner_zone_offsets=[1, -1, 2, -2])
    state = CalibrationState.from_config(cfg, {})
    text = state.mapping_preview_text()
    assert "Local corner anchor nudges" in text
    assert "+1/-1/+2/-2" in text


def test_corner_refinement_clamps_to_supported_limit() -> None:
    cfg = AppConfig(device_zone_count=8, corner_offsets_enabled=True, corner_zone_offsets=[99, -99, 30, -30])
    state = CalibrationState.from_config(cfg, {})
    assert state.active_corner_zone_offsets() == [24, -24, 24, -24]


def test_corner_refinement_active_offsets_pad_missing_values() -> None:
    cfg = AppConfig(device_zone_count=8, corner_offsets_enabled=True, corner_zone_offsets=[3, -2])
    state = CalibrationState.from_config(cfg, {})
    assert state.active_corner_zone_offsets() == [3, -2, 0, 0]


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


def test_validation_report_tracks_confidence_and_sentinel_consistency() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    report = state.validation_report()
    assert report.confidence_score < MIN_CALIBRATION_VALIDATION_CONFIDENCE
    assert report.direction_confirmed is False
    assert report.cycle_replay_confirmed is False
    assert "direction verification" in " ".join(report.remediation_hints).lower()

    for step_id in (
        "start-point-detection",
        "direction-verification",
        "corner-assignment",
        "edge-refinement",
        "validation-replay",
    ):
        state.mark_calibration_step(step_id, passed=True)
    state.corner_anchor_top_left = report.expected_sentinels[0]
    state.corner_anchor_top_right = report.expected_sentinels[1]
    state.corner_anchor_bottom_right = report.expected_sentinels[2]
    state.corner_anchor_bottom_left = report.expected_sentinels[3]
    passed_report = state.validation_report()
    assert passed_report.confidence_score == 1.0
    assert passed_report.direction_confidence_component == 1.0
    assert passed_report.anchors_confidence_component == 1.0
    assert passed_report.cycle_confidence_component == 1.0
    assert passed_report.outcome_status == "pass"
    assert passed_report.hard_fail is False
    assert passed_report.sentinel_consistency is True
    assert state.can_complete_calibration_flow() is True


def test_validation_report_fails_when_sentinels_mismatch_under_strict_policy() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    for step_id in state.calibration_steps():
        state.mark_calibration_step(step_id, passed=True)
    expected = state.validation_report().expected_sentinels
    shifted = tuple((value + 1) % state.effective_device_zone_count() for value in expected)
    state.corner_anchor_top_left = shifted[0]
    state.corner_anchor_top_right = shifted[1]
    state.corner_anchor_bottom_right = shifted[2]
    state.corner_anchor_bottom_left = shifted[3]

    report = state.validation_report()
    assert report.confidence_score == 1.0
    assert report.sentinel_consistency is False
    assert report.outcome_status == "fail"
    assert report.hard_fail is True
    assert "sentinel mismatch" not in report.compact_summary().lower()
    assert state.can_complete_calibration_flow() is False


def test_state_checkpoint_restore_round_trips_phase_progress() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    state.mark_calibration_step("start-point-detection", passed=True, notes="confirmed")
    state.mark_calibration_step("direction-verification", passed=True, notes="forward")
    state.zone_offset = 5
    state.reverse_zones = True
    checkpoint = state.save_checkpoint()

    state.mark_calibration_step("direction-verification", passed=False, notes="regressed")
    state.zone_offset = -3
    state.reverse_zones = False

    restored = state.restore_checkpoint(checkpoint)
    assert restored is True
    assert state.zone_offset == 5
    assert state.reverse_zones is True
    assert state.calibration_step_state("direction-verification").passed is True


def test_state_phase_boundary_restore_rewinds_only_from_saved_boundary() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    state.current_phase = "direction-verification"
    state.zone_offset = 2
    state.save_phase_boundary_checkpoint("direction-verification")

    state.zone_offset = 6
    assert state.restore_phase_boundary_checkpoint("direction-verification") is True
    assert state.zone_offset == 2
    assert state.restore_phase_boundary_checkpoint("corner-assignment") is False


def test_zone_count_change_invalidates_dependent_phase_progress() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    for step_id in state.calibration_steps():
        state.mark_calibration_step(step_id, passed=True, notes=f"{step_id} passed")
    expected = state.validation_report().expected_sentinels
    state.corner_anchor_top_left = expected[0]
    state.corner_anchor_top_right = expected[1]
    state.corner_anchor_bottom_right = expected[2]
    state.corner_anchor_bottom_left = expected[3]
    assert state.can_complete_calibration_flow() is True

    invalidated = state.invalidate_for_zone_count_change()

    assert invalidated == (
        "direction-verification",
        "corner-assignment",
        "edge-refinement",
        "validation-replay",
    )
    assert state.calibration_step_state("start-point-detection").passed is True
    for step_id in invalidated:
        progress = state.calibration_step_state(step_id)
        assert progress.complete is False
        assert progress.passed is False
        assert progress.notes == ""
        assert state.phase_completion_flags[step_id] is False
        validation = state.phase_validation_state[step_id]
        assert validation.valid is False
        assert validation.details == ""
    assert state.can_complete_calibration_flow() is False


def test_zone_count_change_only_invalidates_previously_completed_dependent_phases() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    state.mark_calibration_step("start-point-detection", passed=True, notes="ok")
    state.mark_calibration_step("direction-verification", passed=True, notes="ok")
    state.mark_calibration_step("corner-assignment", passed=False, notes="not complete")

    invalidated = state.invalidate_for_zone_count_change()

    assert invalidated == ("direction-verification", "corner-assignment")
    assert state.calibration_step_state("start-point-detection").passed is True
    assert state.calibration_step_state("direction-verification").passed is False
    assert state.calibration_step_state("corner-assignment").passed is False


def test_zone_count_change_dependency_invalidation_tracks_sequence_prerequisite_updates(monkeypatch) -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    for step_id in state.calibration_steps():
        state.mark_calibration_step(step_id, passed=True, notes="ok")

    def _always_pass(_state: CalibrationState, _phase: CalibrationPhaseDefinition) -> tuple[bool, str]:
        return True, "ok"

    patched_sequence = (
        CalibrationPhaseDefinition(
            step_id="start-point-detection",
            title="start",
            mode="start-point identification",
            prerequisites=(),
            required_actions=(),
            validation_fn=_always_pass,
            remediation_hints=(),
            pass_criteria="",
            fail_criteria="",
        ),
        CalibrationPhaseDefinition(
            step_id="direction-verification",
            title="direction",
            mode="direction walk",
            prerequisites=("start-point-detection",),
            required_actions=(),
            validation_fn=_always_pass,
            remediation_hints=(),
            pass_criteria="",
            fail_criteria="",
        ),
        CalibrationPhaseDefinition(
            step_id="corner-assignment",
            title="corner",
            mode="corner+offset alignment",
            prerequisites=("direction-verification",),
            required_actions=(),
            validation_fn=_always_pass,
            remediation_hints=(),
            pass_criteria="",
            fail_criteria="",
        ),
        CalibrationPhaseDefinition(
            step_id="validation-replay",
            title="replay",
            mode="coverage sanity",
            prerequisites=("corner-assignment",),
            required_actions=(),
            validation_fn=_always_pass,
            remediation_hints=(),
            pass_criteria="",
            fail_criteria="",
        ),
        CalibrationPhaseDefinition(
            step_id="edge-refinement",
            title="edge",
            mode="fine offset",
            prerequisites=("validation-replay",),
            required_actions=(),
            validation_fn=_always_pass,
            remediation_hints=(),
            pass_criteria="",
            fail_criteria="",
        ),
    )
    monkeypatch.setattr("nanoleaf_sync.ui.calibration_state.CALIBRATION_SEQUENCE", patched_sequence)
    invalidated = state.invalidate_for_zone_count_change(affected_phases=ZONE_COUNT_DIRECTLY_AFFECTED_PHASES)

    assert invalidated == (
        "direction-verification",
        "corner-assignment",
        "validation-replay",
        "edge-refinement",
    )


def test_calibration_step_markers_emit_non_sensitive_phase_events(caplog) -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    with caplog.at_level(logging.INFO):
        state.mark_calibration_step("direction-verification", passed=False, notes="Phase is not marked as passed yet.")

    assert "telemetry.calibration.phase_complete phase=direction-verification passed=False" in caplog.text
    assert "failure_cause=not_marked_passed" in caplog.text


def test_calibration_flow_markers_emit_blocked_and_evaluated_events(caplog) -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    with caplog.at_level(logging.INFO):
        assert state.can_complete_calibration_flow() is False
    assert "telemetry.calibration.flow_blocked phase=start-point-detection" in caplog.text

    caplog.clear()
    for step_id in state.calibration_steps():
        state.mark_calibration_step(step_id, passed=True)
    expected = state.validation_report().expected_sentinels
    state.corner_anchor_top_left = expected[0]
    state.corner_anchor_top_right = expected[1]
    state.corner_anchor_bottom_right = expected[2]
    state.corner_anchor_bottom_left = expected[3]
    with caplog.at_level(logging.INFO):
        assert state.can_complete_calibration_flow() is True
    assert "telemetry.calibration.flow_evaluated allowed=True outcome=pass confidence=1.00" in caplog.text
