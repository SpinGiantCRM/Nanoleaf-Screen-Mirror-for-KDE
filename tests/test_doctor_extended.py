"""Additional tests for tools/doctor.py uncovered functions and edge cases."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.tools import doctor
from nanoleaf_sync.tools.doctor import (
    DoctorCheck,
    _check_calibration_completeness,
    _check_dependencies,
    _check_desktop_authorization,
    _check_mode_consistency,
    _check_probe_status,
    _check_python_runtime,
    _check_session_bus,
    _normalized_backend,
    _run_probe_sync,
    format_report,
    run_doctor,
)


# ---------------------------------------------------------------------------
# _check_python_runtime
# ---------------------------------------------------------------------------


def test_python_runtime_pass() -> None:
    result = _check_python_runtime()
    assert result.status == "pass"
    assert result.name == "python"
    assert "Python" in result.message


def test_python_runtime_fail_for_old_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "version_info", (3, 10, 0, "final", 0))
    result = _check_python_runtime()
    assert result.status == "fail"


# ---------------------------------------------------------------------------
# _check_dependencies
# ---------------------------------------------------------------------------


def test_dependencies_all_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.importlib, "import_module", lambda mod: None)
    result = _check_dependencies()
    assert result.status == "pass"


def test_dependencies_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = doctor.importlib.import_module

    def _conditional_import(mod: str) -> None:
        if mod == "PyQt6":
            raise ImportError("No module named PyQt6")
        return original_import(mod) if mod not in ("numpy", "dbus_next", "hid") else None

    monkeypatch.setattr(doctor.importlib, "import_module", _conditional_import)
    result = _check_dependencies()
    assert result.status == "fail"
    assert "PyQt6" in result.message


# ---------------------------------------------------------------------------
# _check_session_bus
# ---------------------------------------------------------------------------


def test_session_bus_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    result = _check_session_bus()
    assert result.status == "pass"


def test_session_bus_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    result = _check_session_bus()
    assert result.status == "fail"
    assert "not set" in result.message.lower()


# ---------------------------------------------------------------------------
# _check_mode_consistency
# ---------------------------------------------------------------------------


def test_mode_consistency_pass_with_mock() -> None:
    result = _check_mode_consistency(AppConfig(use_mock_capture=True))
    assert result.status == "pass"


def test_mode_consistency_pass_with_valid_backend() -> None:
    result = _check_mode_consistency(AppConfig(use_mock_capture=False, prefer_backend="kwin-dbus"))
    assert result.status == "pass"


def test_mode_consistency_fail_with_invalid_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    # Make normalize_backend_preference return an invalid backend name
    monkeypatch.setattr(doctor, "normalize_backend_preference", lambda x: "invalid-backend")
    result = _check_mode_consistency(AppConfig(use_mock_capture=False, prefer_backend="invalid"))
    assert result.status == "fail"


# ---------------------------------------------------------------------------
# _check_probe_status
# ---------------------------------------------------------------------------


def test_probe_status_explicit_backend() -> None:
    result = _check_probe_status(AppConfig(prefer_backend="kwin-dbus"))
    assert result.status == "pass"
    assert "Selection reason=explicit" in result.message


def test_probe_status_auto_with_cached_winner() -> None:
    result = _check_probe_status(
        AppConfig(
            prefer_backend="auto",
            auto_selected_backend="kwin-dbus",
            auto_probe_signature="testsig",
            auto_probe_timestamp="2025-01-01",
            auto_probe_enabled=True,
        )
    )
    assert result.status == "pass"
    assert "cached_winner=kwin-dbus" in result.message
    assert "selection_reason=cached-probe" in result.message


def test_probe_status_auto_no_cache() -> None:
    result = _check_probe_status(
        AppConfig(
            prefer_backend="auto",
            auto_selected_backend="",
            auto_probe_enabled=True,
        )
    )
    assert result.status == "warn"
    assert "no cached winner" in result.message


def test_probe_status_auto_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NANOLEAF_DISABLE_CAPTURE_PROBE", "true")
    result = _check_probe_status(AppConfig(prefer_backend="auto", auto_probe_enabled=False))
    assert "effective_enabled=False" in result.message


def test_probe_status_auto_enabled_no_override() -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("NANOLEAF_DISABLE_CAPTURE_PROBE", raising=False)
        result = _check_probe_status(AppConfig(prefer_backend="auto", auto_probe_enabled=True))
    assert "effective_enabled=True" in result.message


# ---------------------------------------------------------------------------
# _check_calibration_completeness
# ---------------------------------------------------------------------------


def test_calibration_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    from nanoleaf_sync.runtime.calibration_resolver import CalibrationMappingSnapshot

    fake_snapshot = CalibrationMappingSnapshot(
        device_to_source_indices=list(range(48)),
        mode="corner_anchored",
        direction="forward",
        validation_warnings=(),
        warning_codes=(),
        calibration_model="corner_anchored",
        strategy="full",
    )
    monkeypatch.setattr(
        doctor, "resolve_calibration_mapping_from_config", lambda **kw: fake_snapshot
    )
    result = _check_calibration_completeness(AppConfig(device_zone_count=48))
    assert result.status == "pass"


def test_calibration_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    from nanoleaf_sync.runtime.calibration_resolver import CalibrationMappingSnapshot

    fake_snapshot = CalibrationMappingSnapshot(
        device_to_source_indices=[],
        mode="corner_anchored",
        direction="forward",
        validation_warnings=("Missing corner anchors",),
        warning_codes=("missing_anchors",),
        calibration_model="corner_anchored",
        strategy="full",
    )
    monkeypatch.setattr(
        doctor, "resolve_calibration_mapping_from_config", lambda **kw: fake_snapshot
    )
    result = _check_calibration_completeness(AppConfig(device_zone_count=48))
    assert result.status == "warn"
    assert result.action is not None and "assign all four" in result.action.lower()


# ---------------------------------------------------------------------------
# _normalized_backend
# ---------------------------------------------------------------------------


def test_normalized_backend_non_empty() -> None:
    result = _normalized_backend(AppConfig(prefer_backend="kwin-dbus"))
    assert result == "kwin-dbus"


def test_normalized_backend_empty() -> None:
    result = _normalized_backend(AppConfig(prefer_backend=""))
    assert result == ""


# ---------------------------------------------------------------------------
# _check_desktop_authorization edge cases
# ---------------------------------------------------------------------------


def test_desktop_authorization_no_files_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    autostart = tmp_path / "nonexistent-autostart.desktop"
    template = tmp_path / "nonexistent-template.desktop"

    monkeypatch.setattr(doctor, "user_autostart_path", lambda: autostart)
    monkeypatch.setattr(doctor, "installed_desktop_entry_candidates", lambda: [])
    monkeypatch.setattr(doctor, "source_desktop_template_path", lambda: template)

    result = _check_desktop_authorization()
    assert result.status == "warn"
    assert "No desktop entry found" in result.message


def test_desktop_authorization_template_no_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    autostart = tmp_path / "nonexistent-autostart.desktop"
    template = tmp_path / "repo-docs.desktop"
    template.write_text("[Desktop Entry]\n", encoding="utf-8")

    monkeypatch.setattr(doctor, "user_autostart_path", lambda: autostart)
    monkeypatch.setattr(doctor, "installed_desktop_entry_candidates", lambda: [])
    monkeypatch.setattr(doctor, "source_desktop_template_path", lambda: template)

    result = _check_desktop_authorization()
    assert "missing restricted interface marker" in result.message


def test_desktop_authorization_autostart_no_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    autostart = tmp_path / "home-autostart.desktop"
    autostart.write_text("[Desktop Entry]\nName=Foo\n", encoding="utf-8")

    monkeypatch.setattr(doctor, "user_autostart_path", lambda: autostart)

    result = _check_desktop_authorization()
    assert result.status == "warn"
    assert "missing restricted interface marker" in result.message.lower()


def test_desktop_authorization_autostart_with_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    autostart = tmp_path / "home-autostart.desktop"
    autostart.write_text(f"[Desktop Entry]\n{doctor.RESTRICTED_IFACE_MARKER}\n", encoding="utf-8")

    monkeypatch.setattr(doctor, "user_autostart_path", lambda: autostart)

    result = _check_desktop_authorization()
    assert result.status == "pass"


def test_desktop_authorization_installed_no_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    autostart = tmp_path / "nonexistent-autostart.desktop"
    installed = tmp_path / "usr" / "share" / "applications" / "nanoleaf-kde-sync.desktop"
    installed.parent.mkdir(parents=True, exist_ok=True)
    installed.write_text("[Desktop Entry]\nName=Foo\n", encoding="utf-8")
    template = tmp_path / "nonexistent-template.desktop"

    monkeypatch.setattr(doctor, "user_autostart_path", lambda: autostart)
    monkeypatch.setattr(doctor, "installed_desktop_entry_candidates", lambda: [installed])
    monkeypatch.setattr(doctor, "source_desktop_template_path", lambda: template)

    result = _check_desktop_authorization()
    assert "missing restricted interface marker" in result.message


# ---------------------------------------------------------------------------
# _run_probe_sync
# ---------------------------------------------------------------------------


def test_run_probe_sync_no_running_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _probe_pass() -> DoctorCheck:
        return DoctorCheck("kwin-screenshot2", "pass", "ok")

    monkeypatch.setattr(doctor, "_probe_kwin_screenshot2", _probe_pass)
    result = _run_probe_sync()
    assert result.status == "pass"


# ---------------------------------------------------------------------------
# run_doctor with various config scenarios
# ---------------------------------------------------------------------------


def test_run_doctor_auto_backend_default_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_config(
        monkeypatch, AppConfig(device_vid=0x37FA, device_pid=0x8201, prefer_backend="auto")
    )
    _patch_checks_pass(monkeypatch)

    async def _probe_pass() -> DoctorCheck:
        return DoctorCheck("kwin-screenshot2", "pass", "ok")

    monkeypatch.setattr(doctor, "_probe_kwin_screenshot2", _probe_pass)

    checks = run_doctor()
    assert len(checks) >= 5
    names = {c.name for c in checks}
    assert "kwin-screenshot2" in names
    assert "desktop-authorization" in names


def test_run_doctor_mock_capture_skips_kwin(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_config(
        monkeypatch,
        AppConfig(device_vid=0x37FA, device_pid=0x8201, use_mock_capture=True),
    )
    _patch_checks_pass(monkeypatch)

    # _run_probe_sync should NOT be called for mock capture
    monkeypatch.setattr(
        doctor,
        "_run_probe_sync",
        lambda: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    monkeypatch.setattr(
        doctor,
        "_check_desktop_authorization",
        lambda: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    checks = run_doctor()
    names = {c.name for c in checks}
    assert "kwin-screenshot2" not in names
    assert "desktop-authorization" not in names


def test_run_doctor_with_device_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_config(monkeypatch, AppConfig(device_vid=0x37FA, device_pid=0x8201))
    _patch_checks_pass(monkeypatch)

    monkeypatch.setattr(
        doctor,
        "_check_real_device_probe",
        lambda cfg: DoctorCheck("device-probe", "pass", "device ok"),
    )

    checks = run_doctor(include_device_probe=True)
    names = {c.name for c in checks}
    assert "device-probe" in names


def test_run_doctor_device_probe_vid_pid_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_config(monkeypatch, AppConfig(device_vid=0, device_pid=0))
    _patch_checks_pass(monkeypatch)

    checks = run_doctor(include_device_probe=True)
    device_check = next(c for c in checks if c.name == "device-probe")
    assert device_check.status == "fail"
    assert "VID/PID" in device_check.message


def test_run_doctor_with_capture_probe_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_config(monkeypatch, AppConfig(device_vid=0x37FA, device_pid=0x8201))
    _patch_checks_pass(monkeypatch)

    monkeypatch.setattr(
        doctor,
        "_check_real_capture_probe",
        lambda cfg: DoctorCheck("capture-probe", "pass", "capture ok"),
    )

    checks = run_doctor(include_capture_probe=True)
    capture_check = next(c for c in checks if c.name == "capture-probe")
    assert capture_check.status == "pass"


# ---------------------------------------------------------------------------
# format_report edge cases
# ---------------------------------------------------------------------------


def test_format_report_empty() -> None:
    report = format_report([])
    assert "PASS (0)" in report
    assert "WARN (0)" in report
    assert "FAIL (0)" in report
    assert "- none" in report


def test_format_report_all_fail() -> None:
    checks = [
        DoctorCheck("a", "fail", "boom", "fix it"),
        DoctorCheck("b", "fail", "also boom"),
    ]
    report = format_report(checks)
    assert "FAIL (2)" in report
    assert "PASS (0)" in report
    assert "WARN (0)" in report


def test_format_report_mixed() -> None:
    checks = [
        DoctorCheck("a", "pass", "ok"),
        DoctorCheck("b", "warn", "hmm", "action1"),
        DoctorCheck("c", "fail", "bad", "action2"),
        DoctorCheck("d", "pass", "fine"),
    ]
    report = format_report(checks)
    assert "PASS (2)" in report
    assert "WARN (1)" in report
    assert "FAIL (1)" in report
    assert "Action: action1" in report
    assert "Action: action2" in report


# ---------------------------------------------------------------------------
# DoctorCheck dataclass
# ---------------------------------------------------------------------------


def test_doctor_check_properties() -> None:
    c = DoctorCheck("test", "pass", "ok")
    assert c.name == "test"
    assert c.status == "pass"
    assert c.message == "ok"
    assert c.action == ""


def test_doctor_check_with_action() -> None:
    c = DoctorCheck("test", "fail", "bad", "Run setup")
    assert c.action == "Run setup"


def test_doctor_check_immutable() -> None:
    c = DoctorCheck("test", "pass", "ok")
    with pytest.raises(Exception):
        c.name = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------


def test_main_all_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_config(monkeypatch, AppConfig(device_vid=0x37FA, device_pid=0x8201))
    _patch_checks_pass(monkeypatch)
    monkeypatch.setattr(
        doctor, "_check_hid_enumeration", lambda cfg: DoctorCheck("hid-device", "pass", "ok")
    )
    monkeypatch.setattr(
        doctor,
        "_check_desktop_authorization",
        lambda: DoctorCheck("desktop-authorization", "pass", "ok"),
    )
    monkeypatch.setattr(
        doctor, "_run_probe_sync", lambda: DoctorCheck("kwin-screenshot2", "pass", "ok")
    )

    result = doctor.main([])
    assert result == 0


def test_main_with_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_config(monkeypatch, AppConfig(device_vid=0x37FA, device_pid=0x8201))
    monkeypatch.setattr(
        doctor, "_check_python_runtime", lambda: DoctorCheck("python", "fail", "old python")
    )
    monkeypatch.setattr(
        doctor, "_check_dependencies", lambda: DoctorCheck("dependencies", "pass", "ok")
    )
    monkeypatch.setattr(
        doctor, "_check_session_bus", lambda: DoctorCheck("session-bus", "pass", "ok")
    )
    monkeypatch.setattr(
        doctor, "_check_mode_consistency", lambda cfg: DoctorCheck("mode-consistency", "pass", "ok")
    )
    monkeypatch.setattr(
        doctor,
        "_check_calibration_completeness",
        lambda cfg: DoctorCheck("calibration", "pass", "ok"),
    )
    monkeypatch.setattr(
        doctor, "_check_probe_status", lambda cfg: DoctorCheck("probe-status", "pass", "ok")
    )
    monkeypatch.setattr(
        doctor, "_check_hid_enumeration", lambda cfg: DoctorCheck("hid-device", "pass", "ok")
    )
    monkeypatch.setattr(
        doctor,
        "_check_desktop_authorization",
        lambda: DoctorCheck("desktop-authorization", "pass", "ok"),
    )
    monkeypatch.setattr(
        doctor, "_run_probe_sync", lambda: DoctorCheck("kwin-screenshot2", "pass", "ok")
    )

    result = doctor.main([])
    assert result == 1


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _patch_config(monkeypatch, cfg: AppConfig) -> None:
    class _FakeConfigManager:
        def load(self) -> AppConfig:
            return cfg

    monkeypatch.setattr(doctor, "ConfigManager", _FakeConfigManager)
    monkeypatch.setattr(doctor, "validate_config", lambda loaded_cfg: loaded_cfg)


def _patch_checks_pass(monkeypatch) -> None:
    monkeypatch.setattr(
        doctor, "_check_python_runtime", lambda: DoctorCheck("python", "pass", "ok")
    )
    monkeypatch.setattr(
        doctor, "_check_dependencies", lambda: DoctorCheck("dependencies", "pass", "ok")
    )
    monkeypatch.setattr(
        doctor, "_check_session_bus", lambda: DoctorCheck("session-bus", "pass", "ok")
    )
    monkeypatch.setattr(
        doctor, "_check_mode_consistency", lambda cfg: DoctorCheck("mode-consistency", "pass", "ok")
    )
    monkeypatch.setattr(
        doctor,
        "_check_calibration_completeness",
        lambda cfg: DoctorCheck("calibration", "pass", "ok"),
    )
    monkeypatch.setattr(
        doctor, "_check_probe_status", lambda cfg: DoctorCheck("probe-status", "pass", "ok")
    )
    monkeypatch.setattr(
        doctor, "_check_hid_enumeration", lambda cfg: DoctorCheck("hid-device", "pass", "ok")
    )
    monkeypatch.setattr(
        doctor,
        "_check_desktop_authorization",
        lambda: DoctorCheck("desktop-authorization", "pass", "ok"),
    )
    monkeypatch.setattr(
        doctor, "_run_probe_sync", lambda: DoctorCheck("kwin-screenshot2", "pass", "ok")
    )
