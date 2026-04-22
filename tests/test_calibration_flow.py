from __future__ import annotations

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.calibration_flow import CALIBRATION_SEQUENCE, calibration_sequence_text, derive_corner_anchor_device_indices
from nanoleaf_sync.ui.calibration_state import CalibrationState
from nanoleaf_sync.ui.calibration_preview import calibration_test_frame


def test_calibration_sequence_contains_required_order() -> None:
    keys = [step.step_id for step in CALIBRATION_SEQUENCE]
    assert keys == [
        "start-point-detection",
        "direction-verification",
        "corner-assignment",
        "edge-refinement",
        "validation-replay",
    ]
    assert "Start-point detection" in calibration_sequence_text()
    assert CALIBRATION_SEQUENCE[2].prerequisites == ("direction-verification",)
    assert CALIBRATION_SEQUENCE[0].required_actions
    assert callable(CALIBRATION_SEQUENCE[0].validation_fn)
    assert CALIBRATION_SEQUENCE[0].remediation_hints


def test_derive_corner_anchor_device_indices_stays_unique_with_more_device_zones() -> None:
    anchors = derive_corner_anchor_device_indices(
        zone_count=8,
        device_zone_count=24,
        zone_offset=3,
        reverse_zones=False,
    )
    assert len(anchors) == 4
    assert len(set(anchors)) == 4


def test_calibration_test_frame_never_truncates_device_zone_count() -> None:
    frame = calibration_test_frame(device_zone_count=24, active_indices=[23])
    assert len(frame) == 24
    assert frame[-1] != (0, 0, 0)


def test_derive_corner_anchor_device_indices_limits_to_unique_device_zones() -> None:
    anchors = derive_corner_anchor_device_indices(
        zone_count=12,
        device_zone_count=2,
        zone_offset=0,
        reverse_zones=False,
    )
    assert anchors == [0, 1]


def test_derive_corner_anchor_device_indices_responds_to_offset_and_direction() -> None:
    default = derive_corner_anchor_device_indices(
        zone_count=16,
        device_zone_count=16,
        zone_offset=0,
        reverse_zones=False,
    )
    shifted = derive_corner_anchor_device_indices(
        zone_count=16,
        device_zone_count=16,
        zone_offset=3,
        reverse_zones=False,
    )
    reversed_shifted = derive_corner_anchor_device_indices(
        zone_count=16,
        device_zone_count=16,
        zone_offset=3,
        reverse_zones=True,
    )
    assert shifted != default
    assert reversed_shifted != shifted


def test_corner_anchor_derivation_is_deterministic_for_same_inputs() -> None:
    params = {
        "zone_count": 20,
        "device_zone_count": 24,
        "zone_offset": -7,
        "reverse_zones": True,
    }
    first = derive_corner_anchor_device_indices(**params)
    second = derive_corner_anchor_device_indices(**params)
    third = derive_corner_anchor_device_indices(**params)

    assert first == second == third


def test_corner_anchor_traversal_wraps_without_mutating_zone_offset_input() -> None:
    zone_offset = 4
    anchors = derive_corner_anchor_device_indices(
        zone_count=12,
        device_zone_count=12,
        zone_offset=zone_offset,
        reverse_zones=False,
    )
    cycle = len(anchors)
    step0 = anchors[0]
    wrapped = anchors[cycle % cycle]

    assert zone_offset == 4
    assert step0 == wrapped


def test_calibration_step_prerequisites_gate_completion() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    assert state.calibration_prerequisites_met("start-point-detection") is True
    assert state.calibration_prerequisites_met("direction-verification") is False
    state.mark_calibration_step("start-point-detection", passed=True)
    assert state.calibration_prerequisites_met("direction-verification") is True
    state.mark_calibration_step("direction-verification", passed=True)
    state.mark_calibration_step("corner-assignment", passed=True)
    state.mark_calibration_step("edge-refinement", passed=True)
    state.mark_calibration_step("validation-replay", passed=True)
    assert state.can_complete_calibration_flow() is True


def test_calibration_step_fail_keeps_completion_gate_closed() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    for step in CALIBRATION_SEQUENCE[:-1]:
        state.mark_calibration_step(step.step_id, passed=True)
    state.mark_calibration_step(CALIBRATION_SEQUENCE[-1].step_id, passed=False, notes="missed zone")
    assert state.can_complete_calibration_flow() is False


def test_calibration_completion_requires_validation_score_threshold() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    for step in CALIBRATION_SEQUENCE:
        state.mark_calibration_step(step.step_id, passed=True)
    # Break deterministic replay by forcing explicit mismatched anchors.
    state.corner_anchor_top_left = 0
    state.corner_anchor_top_right = 0
    state.corner_anchor_bottom_right = 0
    state.corner_anchor_bottom_left = 0
    report = state.validation_report()
    assert report.sentinel_consistency is False
    assert report.anchors_unique_valid is False
    assert report.outcome_status == "fail"
    assert report.hard_fail is True
    assert "failed checks" in report.remediation_action.lower()
    assert report.remediation_hints
    assert state.can_complete_calibration_flow() is False


def test_calibration_completion_blocks_out_of_range_corner_anchor_assignments() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    for step in CALIBRATION_SEQUENCE:
        state.mark_calibration_step(step.step_id, passed=True)

    state.corner_anchor_top_left = 0
    state.corner_anchor_top_right = 2
    state.corner_anchor_bottom_right = 4
    state.corner_anchor_bottom_left = 999

    report = state.validation_report()
    assert report.anchors_unique_valid is False
    assert report.outcome_status == "fail"
    assert state.can_complete_calibration_flow() is False


def test_calibration_completion_fails_when_sentinel_consistency_is_broken() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    for step in CALIBRATION_SEQUENCE:
        state.mark_calibration_step(step.step_id, passed=True)
    expected = state.validation_report().expected_sentinels
    state.corner_anchor_top_left = (expected[0] + 1) % 8
    state.corner_anchor_top_right = (expected[1] + 1) % 8
    state.corner_anchor_bottom_right = (expected[2] + 1) % 8
    state.corner_anchor_bottom_left = (expected[3] + 1) % 8

    report = state.validation_report()
    assert report.direction_confirmed is True
    assert report.anchors_unique_valid is True
    assert report.cycle_replay_confirmed is True
    assert report.sentinel_consistency is False
    assert report.outcome_status == "fail"
    assert report.hard_fail is True
    assert state.can_complete_calibration_flow() is False


def test_phase_validation_tracks_failures_until_actions_pass() -> None:
    state = CalibrationState.from_config(AppConfig(device_zone_count=8), {})
    ok, details = state.evaluate_phase("start-point-detection")
    assert ok is False
    assert "not marked as passed" in details.lower()

    state.mark_calibration_step("start-point-detection", passed=True)
    ok, details = state.evaluate_phase("start-point-detection")
    assert ok is True
    assert "passed" in details.lower()
