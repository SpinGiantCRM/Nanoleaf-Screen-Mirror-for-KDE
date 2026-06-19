from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig, ZoneConfig
from nanoleaf_sync.runtime.readiness_check import (
    CAPTURE_PROBLEM_STATUS,
    CONFIG_PROBLEM_STATUS,
    DEVICE_PROBLEM_STATUS,
    NEEDS_CALIBRATION_STATUS,
    READY_STATUS,
    ReadinessIssue,
    ReadinessReport,
    run_readiness_check,
)


def _valid_config() -> AppConfig:
    calibration = CalibrationConfig(
        device_zone_count=4,
        corner_anchor_top_left=0,
        corner_anchor_top_right=1,
        corner_anchor_bottom_right=2,
        corner_anchor_bottom_left=3,
    )
    zones = [
        ZoneConfig(x=0.0, y=0.0, w=0.25, h=0.25),
        ZoneConfig(x=0.25, y=0.0, w=0.25, h=0.25),
        ZoneConfig(x=0.5, y=0.0, w=0.25, h=0.25),
        ZoneConfig(x=0.75, y=0.0, w=0.25, h=0.25),
    ]
    return AppConfig(
        device_zone_count=4,
        calibration=calibration,
        zones=zones,
        wizard_completed=True,
        wizard_in_progress_state="",
    )


def _check(
    cfg: AppConfig,
    *,
    runtime_status: dict | None = None,
    source_zone_count: int | None = None,
    capture_probe=None,
    device_probe=None,
) -> ReadinessReport:
    return run_readiness_check(
        config=cfg,
        runtime_status=runtime_status if runtime_status is not None else {},
        source_zone_count=source_zone_count if source_zone_count is not None else 4,
        capture_probe=capture_probe if capture_probe is not None else (lambda _cfg: None),
        device_probe=device_probe if device_probe is not None else (lambda _cfg: None),
    )


# ===========================================================================
# Happy path
# ===========================================================================


def test_ready_when_everything_ok() -> None:
    report = _check(
        _valid_config(),
        runtime_status={"running": False, "consecutive_errors": 0, "max_consecutive_errors": 5},
    )
    assert report.status == READY_STATUS
    assert report.issues == ()
    assert report.ready is True


def test_ready_when_running_with_no_errors() -> None:
    """Running but no consecutive errors should still report ready."""
    report = _check(
        _valid_config(),
        runtime_status={"running": True, "consecutive_errors": 0, "max_consecutive_errors": 5},
    )
    assert report.status == READY_STATUS


# ===========================================================================
# Zone count validation
# ===========================================================================


def test_strip_count_not_set_returns_config_problem() -> None:
    cfg = replace(_valid_config(), device_zone_count=0, zones=[])
    cfg.calibration.device_zone_count = 0
    report = _check(cfg)
    assert any(issue.check == "strip-count" for issue in report.issues)
    assert any(issue.category == CONFIG_PROBLEM_STATUS for issue in report.issues)


def test_source_zone_count_mismatch_returns_needs_calibration() -> None:
    cfg = _valid_config()
    report = _check(cfg, source_zone_count=6)  # 6 source zones ≠ 4 manual zones
    assert any(issue.check == "source-zone-count" for issue in report.issues)
    assert any(issue.category == NEEDS_CALIBRATION_STATUS for issue in report.issues)


def test_source_zone_count_matches_clean() -> None:
    cfg = _valid_config()
    report = _check(cfg, source_zone_count=4)
    assert not any(issue.check == "source-zone-count" for issue in report.issues)


def test_source_zone_count_falls_back_to_zone_list_length() -> None:
    """When source_zone_count is None, it's derived from len(normalized.zones)."""
    cfg = _valid_config()
    # 4 zones in config, manual count=4, no explicit source → should match
    report = run_readiness_check(
        config=cfg,
        runtime_status={},
        source_zone_count=None,
        capture_probe=lambda _c: None,
        device_probe=lambda _c: None,
    )
    assert not any(issue.check == "source-zone-count" for issue in report.issues)


def test_source_zone_count_zero_zones_with_manual_count() -> None:
    """When zones list is empty but manual count is set, mismatch should be detected."""
    cfg = replace(_valid_config(), zones=[])
    report = _check(cfg, source_zone_count=0)
    assert any(issue.check == "source-zone-count" for issue in report.issues)


def test_source_zone_count_zero_with_zero_manual_count() -> None:
    """When both zones and manual count are 0, only strip-count fires (not mismatch)."""
    cfg = replace(_valid_config(), device_zone_count=0, zones=[])
    cfg.calibration.device_zone_count = 0
    report = _check(cfg, source_zone_count=0)
    assert any(issue.check == "strip-count" for issue in report.issues)
    assert not any(issue.check == "source-zone-count" for issue in report.issues)


# ===========================================================================
# Corner anchor validation
# ===========================================================================


def test_missing_corner_anchor_returns_needs_calibration() -> None:
    cfg = _valid_config()
    cfg.calibration.corner_anchor_bottom_left = -1
    report = _check(cfg)
    assert report.status == NEEDS_CALIBRATION_STATUS
    assert any(issue.check == "anchors" for issue in report.issues)
    assert any(issue.fix == "Assign all four corners" for issue in report.issues)


def test_all_anchors_valid_no_issue() -> None:
    cfg = _valid_config()
    report = _check(cfg)
    assert not any(issue.check == "anchors" for issue in report.issues)


def test_calibration_mapping_unresolvable() -> None:
    """When anchors produce a mapping with validation_warnings or wrong length."""
    cfg = _valid_config()
    # Duplicate anchors should cause mapping issues
    cfg.calibration.corner_anchor_bottom_left = cfg.calibration.corner_anchor_top_left  # duplicate
    report = _check(cfg)
    assert any(issue.check == "calibration-mapping" for issue in report.issues)


# ===========================================================================
# Wizard draft detection
# ===========================================================================


def test_stale_wizard_draft_after_completion_returns_config_problem() -> None:
    cfg = replace(_valid_config(), wizard_in_progress_state='{"flow_index":1}')
    report = _check(cfg)
    assert report.status == CONFIG_PROBLEM_STATUS
    assert any(issue.check == "wizard-draft" for issue in report.issues)


def test_wizard_draft_not_reported_when_wizard_not_completed() -> None:
    """Draft is expected (not an issue) before wizard completion."""
    cfg = replace(
        _valid_config(), wizard_completed=False, wizard_in_progress_state='{"flow_index":1}'
    )
    report = _check(cfg)
    assert not any(issue.check == "wizard-draft" for issue in report.issues)


def test_wizard_draft_not_reported_when_state_is_empty() -> None:
    cfg = replace(_valid_config(), wizard_completed=True, wizard_in_progress_state="")
    report = _check(cfg)
    assert not any(issue.check == "wizard-draft" for issue in report.issues)


def test_wizard_draft_not_reported_when_state_whitespace_only() -> None:
    cfg = replace(_valid_config(), wizard_completed=True, wizard_in_progress_state="   ")
    report = _check(cfg)
    assert not any(issue.check == "wizard-draft" for issue in report.issues)


# ===========================================================================
# Runtime loop stuck detection
# ===========================================================================


def test_runtime_loop_stuck_when_errors_equal_max() -> None:
    report = _check(
        _valid_config(),
        runtime_status={"running": True, "consecutive_errors": 5, "max_consecutive_errors": 5},
    )
    assert any(issue.check == "runtime-loop" for issue in report.issues)


def test_runtime_loop_stuck_when_errors_exceed_max() -> None:
    report = _check(
        _valid_config(),
        runtime_status={"running": True, "consecutive_errors": 10, "max_consecutive_errors": 5},
    )
    assert any(issue.check == "runtime-loop" for issue in report.issues)


def test_runtime_loop_below_threshold_no_issue() -> None:
    report = _check(
        _valid_config(),
        runtime_status={"running": True, "consecutive_errors": 4, "max_consecutive_errors": 5},
    )
    assert not any(issue.check == "runtime-loop" for issue in report.issues)


def test_runtime_loop_not_running_no_issue() -> None:
    report = _check(
        _valid_config(),
        runtime_status={
            "running": False,
            "consecutive_errors": 10,
            "max_consecutive_errors": 5,
        },
    )
    assert not any(issue.check == "runtime-loop" for issue in report.issues)


def test_runtime_loop_missing_max_consecutive_errors_field() -> None:
    """When max_consecutive_errors field is missing, defaults to 1."""
    report = _check(
        _valid_config(),
        runtime_status={"running": True, "consecutive_errors": 2},
    )
    assert any(issue.check == "runtime-loop" for issue in report.issues)


# ===========================================================================
# Device probe — error messages and fix text
# ===========================================================================


def test_device_probe_error_with_permission_gives_udev_fix() -> None:
    report = _check(
        _valid_config(),
        device_probe=lambda _cfg: "Access denied by udev rules",
    )
    assert report.status == DEVICE_PROBLEM_STATUS
    assert any(
        issue.check == "hid-device" and issue.fix == "Run udev setup" for issue in report.issues
    )


def test_device_probe_error_with_access_gives_udev_fix() -> None:
    report = _check(
        _valid_config(),
        device_probe=lambda _cfg: "USB access error",
    )
    assert report.status == DEVICE_PROBLEM_STATUS
    assert any(
        issue.check == "hid-device" and issue.fix == "Run udev setup" for issue in report.issues
    )


def test_device_probe_error_with_udev_gives_udev_fix() -> None:
    report = _check(
        _valid_config(),
        device_probe=lambda _cfg: "udev rule missing",
    )
    assert report.status == DEVICE_PROBLEM_STATUS
    assert any(
        issue.check == "hid-device" and issue.fix == "Run udev setup" for issue in report.issues
    )


def test_device_probe_generic_error_gives_reconnect_fix() -> None:
    report = _check(
        _valid_config(),
        device_probe=lambda _cfg: "device disconnected",
    )
    assert any(
        issue.check == "hid-device" and issue.fix == "Reconnect the Nanoleaf strip"
        for issue in report.issues
    )


def test_device_probe_exception_rather_than_error_string() -> None:
    """When device_probe raises an exception (not just returns error string)."""

    def _raising_probe(_cfg: AppConfig) -> str | None:
        raise OSError("could not open device")

    report = _check(_valid_config(), device_probe=_raising_probe)
    assert report.status == DEVICE_PROBLEM_STATUS
    assert any(
        issue.check == "hid-device" and "could not open device" in issue.reason
        for issue in report.issues
    )


# ===========================================================================
# Capture probe
# ===========================================================================


def test_capture_probe_error_returns_capture_problem() -> None:
    report = _check(
        _valid_config(),
        capture_probe=lambda _cfg: "kwin unavailable",
    )
    assert report.status == CAPTURE_PROBLEM_STATUS
    assert any(
        issue.check == "capture-backend" and issue.fix == "Select another capture backend"
        for issue in report.issues
    )


def test_capture_probe_exception_rather_than_error_string() -> None:
    """When capture_probe raises an exception."""

    def _raising_probe(_cfg: AppConfig) -> str | None:
        raise RuntimeError("backend crashed")

    report = _check(_valid_config(), capture_probe=_raising_probe)
    assert report.status == CAPTURE_PROBLEM_STATUS
    assert any(
        issue.check == "capture-backend" and "backend crashed" in issue.reason
        for issue in report.issues
    )


# ===========================================================================
# Error category prioritization
# ===========================================================================


def test_device_problem_takes_priority_over_capture() -> None:
    """DEVICE > CAPTURE when both fail."""
    report = _check(
        _valid_config(),
        capture_probe=lambda _cfg: "capture failed",
        device_probe=lambda _cfg: "device not found",
    )
    assert report.status == DEVICE_PROBLEM_STATUS


def test_device_problem_takes_priority_over_calibration() -> None:
    """DEVICE > CALIBRATION when device probe fails and anchors are missing."""
    cfg = _valid_config()
    cfg.calibration.corner_anchor_bottom_left = -1  # needs calibration
    report = _check(
        cfg,
        device_probe=lambda _cfg: "device not found",
    )
    assert report.status == DEVICE_PROBLEM_STATUS


def test_capture_problem_takes_priority_over_calibration() -> None:
    """CAPTURE > CALIBRATION when capture probe fails and anchors are missing."""
    cfg = _valid_config()
    cfg.calibration.corner_anchor_bottom_left = -1  # needs calibration
    report = _check(
        cfg,
        capture_probe=lambda _cfg: "capture failed",
    )
    assert report.status == CAPTURE_PROBLEM_STATUS


def test_needs_calibration_takes_priority_over_config() -> None:
    """NEEDS_CALIBRATION > CONFIG when anchors missing and zone count mismatched."""
    cfg = _valid_config()
    cfg.calibration.corner_anchor_bottom_left = -1  # needs calibration
    report = _check(cfg, source_zone_count=6)  # zone mismatch → config
    assert report.status == NEEDS_CALIBRATION_STATUS


def test_config_problem_as_fallback() -> None:
    """When only config-level issues exist, status is CONFIG_PROBLEM."""
    report = _check(
        _valid_config(),
        runtime_status={"running": True, "consecutive_errors": 10, "max_consecutive_errors": 5},
    )
    assert report.status == CONFIG_PROBLEM_STATUS


# ===========================================================================
# ReadinessReport and ReadinessIssue dataclass
# ===========================================================================


def test_readiness_report_ready_property_true() -> None:
    report = ReadinessReport(status=READY_STATUS, issues=())
    assert report.ready is True


def test_readiness_report_ready_property_false_with_issues() -> None:
    report = ReadinessReport(
        status=CONFIG_PROBLEM_STATUS,
        issues=(
            ReadinessIssue(
                check="test",
                reason="test reason",
                fix="test fix",
                category=CONFIG_PROBLEM_STATUS,
            ),
        ),
    )
    assert report.ready is False


def test_readiness_report_ready_property_false_with_non_ready_status() -> None:
    report = ReadinessReport(status=NEEDS_CALIBRATION_STATUS, issues=())
    assert report.ready is False


def test_readiness_issue_fields_preserved() -> None:
    issue = ReadinessIssue(
        check="test-check",
        reason="test reason",
        fix="test fix",
        category=DEVICE_PROBLEM_STATUS,
    )
    assert issue.check == "test-check"
    assert issue.reason == "test reason"
    assert issue.fix == "test fix"
    assert issue.category == DEVICE_PROBLEM_STATUS


def test_readiness_issue_is_frozen() -> None:
    issue = ReadinessIssue(check="test-check", reason="r", fix="f", category=CONFIG_PROBLEM_STATUS)
    with pytest.raises(FrozenInstanceError):
        issue.check = "changed"  # type: ignore[misc]


def test_readiness_report_multiple_issues_aggregated() -> None:
    """All issues are included in the report."""
    cfg = _valid_config()
    cfg.calibration.corner_anchor_bottom_left = -1  # anchors
    report = _check(cfg, source_zone_count=6)  # zone count mismatch
    issue_checks = {issue.check for issue in report.issues}
    assert "anchors" in issue_checks
    assert "source-zone-count" in issue_checks


# ===========================================================================
# Edge cases around config entries
# ===========================================================================


def test_device_vid_pid_is_valid_in_default_config() -> None:
    """Default config VID/PID should pass validation."""
    report = _check(_valid_config())
    assert report.status == READY_STATUS


def test_empty_zones_with_nonzero_manual_count() -> None:
    """Empty zones + manual_zone_count > 0 should still calibrate but flag zone mismatch."""
    cfg = replace(_valid_config(), zones=[])
    # calibration.device_zone_count=4 (kept from _valid_config), cfg.device_zone_count=4
    # validate_config resolves to 4 from calibration
    report = _check(cfg, source_zone_count=0)
    assert any(issue.check == "source-zone-count" for issue in report.issues)
