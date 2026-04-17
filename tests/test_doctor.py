from __future__ import annotations

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.tools.doctor import DoctorCheck, _check_mode_consistency, format_report


def test_mode_consistency_replay_without_path_fails() -> None:
    cfg = AppConfig(use_mock_capture=False, prefer_backend="replay", replay_frames_path="")
    result = _check_mode_consistency(cfg)
    assert result.status == "fail"
    assert "replay_frames_path" in result.message


def test_mode_consistency_mock_capture_with_replay_warns() -> None:
    cfg = AppConfig(use_mock_capture=True, prefer_backend="replay")
    result = _check_mode_consistency(cfg)
    assert result.status == "warn"


def test_format_report_groups_entries() -> None:
    checks = [
        DoctorCheck("a", "pass", "ok"),
        DoctorCheck("b", "warn", "careful"),
        DoctorCheck("c", "fail", "boom", "fix"),
    ]
    report = format_report(checks)
    assert "FAIL (1)" in report
    assert "WARN (1)" in report
    assert "PASS (1)" in report
    assert "Action: fix" in report
