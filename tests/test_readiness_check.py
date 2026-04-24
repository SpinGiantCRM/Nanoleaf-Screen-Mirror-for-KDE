from __future__ import annotations

from dataclasses import replace

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig, ZoneConfig
from nanoleaf_sync.runtime.readiness_check import (
    CAPTURE_PROBLEM_STATUS,
    CONFIG_PROBLEM_STATUS,
    DEVICE_PROBLEM_STATUS,
    NEEDS_CALIBRATION_STATUS,
    READY_STATUS,
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


def test_readiness_ready_status() -> None:
    report = run_readiness_check(
        config=_valid_config(),
        runtime_status={"running": False, "consecutive_errors": 0, "max_consecutive_errors": 5},
        source_zone_count=4,
        capture_probe=lambda _cfg: None,
        device_probe=lambda _cfg: None,
    )
    assert report.status == READY_STATUS
    assert report.issues == ()


def test_readiness_needs_calibration_status() -> None:
    cfg = _valid_config()
    cfg.calibration.corner_anchor_bottom_left = -1
    report = run_readiness_check(
        config=cfg,
        runtime_status={},
        source_zone_count=4,
        capture_probe=lambda _cfg: None,
        device_probe=lambda _cfg: None,
    )
    assert report.status == NEEDS_CALIBRATION_STATUS
    assert any(issue.fix == "Assign all four corners" for issue in report.issues)


def test_readiness_device_problem_status() -> None:
    report = run_readiness_check(
        config=_valid_config(),
        runtime_status={},
        source_zone_count=4,
        capture_probe=lambda _cfg: None,
        device_probe=lambda _cfg: "permission denied",
    )
    assert report.status == DEVICE_PROBLEM_STATUS
    assert any(issue.fix == "Run udev setup" for issue in report.issues)


def test_readiness_capture_problem_status() -> None:
    report = run_readiness_check(
        config=_valid_config(),
        runtime_status={},
        source_zone_count=4,
        capture_probe=lambda _cfg: "kwin unavailable",
        device_probe=lambda _cfg: None,
    )
    assert report.status == CAPTURE_PROBLEM_STATUS
    assert any(issue.fix == "Select another capture backend" for issue in report.issues)


def test_readiness_config_problem_status_for_stale_wizard_draft() -> None:
    cfg = replace(_valid_config(), wizard_in_progress_state='{"flow_index":1}')
    report = run_readiness_check(
        config=cfg,
        runtime_status={},
        source_zone_count=4,
        capture_probe=lambda _cfg: None,
        device_probe=lambda _cfg: None,
    )
    assert report.status == CONFIG_PROBLEM_STATUS
    assert any(issue.check == "wizard-draft" for issue in report.issues)
