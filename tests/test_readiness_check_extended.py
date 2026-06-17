"""Additional tests for runtime/readiness_check.py preset validations and probe paths."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.runtime.readiness_check import (
    CONFIG_PROBLEM_STATUS,
    _probe_capture_backend,
    _probe_device,
    run_readiness_check,
)


def _valid_config() -> AppConfig:
    """Create a valid config with calibration and zones."""
    zones = [
        type("Zone", (), {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5})(),
        type("Zone", (), {"x": 0.5, "y": 0.0, "w": 0.5, "h": 0.5})(),
        type("Zone", (), {"x": 0.0, "y": 0.5, "w": 0.5, "h": 0.5})(),
        type("Zone", (), {"x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5})(),
    ]
    cal = CalibrationConfig(
        device_zone_count=4,
        corner_anchor_top_left=0,
        corner_anchor_top_right=3,
        corner_anchor_bottom_right=2,
        corner_anchor_bottom_left=1,
    )
    return AppConfig(
        device_zone_count=4,
        calibration=cal,
        zones=zones,
        wizard_completed=True,
        start_on_launch=False,
    )


# ---------------------------------------------------------------------------
# Config load failure
# ---------------------------------------------------------------------------


def test_config_load_failure_captured() -> None:
    """When validate_config raises, report returns CONFIG_PROBLEM_STATUS."""
    # validate_config validates raw values, so invalid presets get normalized.
    # The real way to trigger config-load failure is via a validate_config exception.
    cfg = AppConfig(device_zone_count=0, device_vid=0)  # invalid VID

    def _failing_validate(c: AppConfig) -> AppConfig:
        raise ValueError("config is broken")

    with patch("nanoleaf_sync.runtime.readiness_check.validate_config", _failing_validate):
        report = run_readiness_check(
            config=cfg,
            runtime_status={},
            source_zone_count=None,
            capture_probe=lambda _c: None,
            device_probe=lambda _c: None,
        )
    assert report.status == CONFIG_PROBLEM_STATUS
    assert any(issue.check == "config-load" for issue in report.issues)
    assert any("broken" in issue.reason for issue in report.issues)


# ---------------------------------------------------------------------------
# validate_config normalizes invalid presets to defaults, so preset
# validation in run_readiness_check acts as a defensive safety net.
# The following test verifies VALID presets produce no issues.
# ---------------------------------------------------------------------------


def test_valid_presets_no_issues() -> None:
    """Config with all valid presets should not report preset issues."""
    cfg = _valid_config()
    report = run_readiness_check(
        config=cfg,
        runtime_status={},
        source_zone_count=4,
        capture_probe=lambda _c: None,
        device_probe=lambda _c: None,
    )
    preset_checks = {
        "preset-layout",
        "preset-edge-locality",
        "preset-quality",
        "preset-motion",
        "preset-color-style",
        "preset-display",
        "hdr-transfer",
        "hdr-primaries",
        "hdr-max-nits",
        "sdr-boost-nits",
    }
    for issue in report.issues:
        assert issue.check not in preset_checks


# ---------------------------------------------------------------------------
# Combined issues: calibration + config
# ---------------------------------------------------------------------------


def test_multiple_issues_from_wizard_and_runtime() -> None:
    """Wizard draft + runtime loop stuck both reported."""
    cfg = replace(_valid_config(), wizard_in_progress_state='{"flow_index":1}')
    report = run_readiness_check(
        config=cfg,
        runtime_status={"running": True, "consecutive_errors": 5, "max_consecutive_errors": 3},
        source_zone_count=4,
        capture_probe=lambda _c: None,
        device_probe=lambda _c: None,
    )
    issue_checks = {issue.check for issue in report.issues}
    assert "wizard-draft" in issue_checks
    assert "runtime-loop" in issue_checks


# ---------------------------------------------------------------------------
# _probe_capture_backend and _probe_device direct tests
# ---------------------------------------------------------------------------


def test_probe_capture_backend_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """_probe_capture_backend should handle missing backends gracefully."""

    # Mock create_capture_backend to return a mock that supports close
    class _MockBackend:
        def close(self) -> None:
            pass

    monkeypatch.setattr(
        "nanoleaf_sync.runtime.readiness_check.create_capture_backend",
        lambda **kw: _MockBackend(),
    )
    monkeypatch.setattr(
        "nanoleaf_sync.runtime.readiness_check._resolve_capture_dims",
        lambda cfg: (64, 36),
    )
    result = _probe_capture_backend(_valid_config())
    assert result is None


def test_probe_device_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """_probe_device should handle missing devices gracefully."""

    class _MockDriver:
        def __init__(self, **kw):
            pass

        def initialize(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr("nanoleaf_sync.runtime.readiness_check.NanoleafUSBDriver", _MockDriver)
    result = _probe_device(_valid_config())
    assert result is None


# ---------------------------------------------------------------------------
# ReadinessReport and ReadinessIssue
# ---------------------------------------------------------------------------


def test_readiness_report_with_only_wizard_draft() -> None:
    cfg = replace(_valid_config(), wizard_in_progress_state='{"flow_index":1}')
    report = run_readiness_check(
        config=cfg,
        runtime_status={},
        source_zone_count=4,
        capture_probe=lambda _c: None,
        device_probe=lambda _c: None,
    )
    assert report.status == CONFIG_PROBLEM_STATUS
    assert any(issue.check == "wizard-draft" for issue in report.issues)
