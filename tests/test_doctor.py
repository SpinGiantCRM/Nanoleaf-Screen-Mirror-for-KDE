from __future__ import annotations

from types import SimpleNamespace

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.tools import doctor
from nanoleaf_sync.tools.doctor import DoctorCheck, _check_mode_consistency, format_report, run_doctor


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


def _patch_config_loader(monkeypatch, cfg: AppConfig) -> None:
    class _FakeConfigManager:
        def load(self) -> AppConfig:
            return cfg

    monkeypatch.setattr(doctor, "ConfigManager", _FakeConfigManager)
    monkeypatch.setattr(doctor, "validate_config", lambda loaded_cfg: loaded_cfg)


def test_run_doctor_full_mock_happy_path(monkeypatch) -> None:
    _patch_config_loader(monkeypatch, AppConfig(use_mock_capture=True, use_mock_device=True))
    monkeypatch.setattr(doctor, "_check_python_runtime", lambda: DoctorCheck("python", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_dependencies", lambda: DoctorCheck("dependencies", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_session_bus", lambda: DoctorCheck("session-bus", "pass", "ok"))
    async def _probe_warn() -> DoctorCheck:
        return DoctorCheck(
            "kwin-screenshot2",
            "warn",
            "ScreenShot2 permission not granted yet.",
            "Approve the ScreenShot2 prompt or restart from the desktop launcher.",
        )

    monkeypatch.setattr(doctor, "_probe_kwin_screenshot2", _probe_warn)
    monkeypatch.setattr(
        doctor,
        "_check_desktop_authorization",
        lambda: DoctorCheck("desktop-authorization", "pass", "desktop marker present"),
    )

    checks = run_doctor()
    report = format_report(checks)

    assert [check.name for check in checks] == [
        "python",
        "dependencies",
        "session-bus",
        "kwin-screenshot2",
        "desktop-authorization",
        "mode-consistency",
        "hid-device",
    ]
    assert "FAIL (0)" in report
    assert "WARN (2)" in report
    assert "PASS (5)" in report
    assert "Action: Approve the ScreenShot2 prompt" in report


def test_run_doctor_real_device_requested_hid_unavailable(monkeypatch) -> None:
    _patch_config_loader(monkeypatch, AppConfig(use_mock_device=False, device_vid=0x37FA, device_pid=0x8201))
    monkeypatch.setattr(doctor, "_check_python_runtime", lambda: DoctorCheck("python", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_dependencies", lambda: DoctorCheck("dependencies", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_session_bus", lambda: DoctorCheck("session-bus", "pass", "ok"))
    async def _probe_pass() -> DoctorCheck:
        return DoctorCheck("kwin-screenshot2", "pass", "ok")

    monkeypatch.setattr(doctor, "_probe_kwin_screenshot2", _probe_pass)
    monkeypatch.setattr(doctor, "_check_desktop_authorization", lambda: DoctorCheck("desktop-authorization", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_real_device_probe", lambda cfg: DoctorCheck("device-probe", "warn", "probe skipped"))
    monkeypatch.setitem(
        doctor.sys.modules,
        "hid",
        SimpleNamespace(enumerate=lambda *_: (_ for _ in ()).throw(RuntimeError("hid backend unavailable"))),
    )

    checks = run_doctor(include_device_probe=True)
    report = format_report(checks)
    hid_check = next(check for check in checks if check.name == "hid-device")

    assert hid_check.status == "fail"
    assert "hid backend unavailable" in hid_check.message
    assert "Install/enable hidapi" in hid_check.action
    assert "FAIL (1)" in report
    assert "Action: Install/enable hidapi" in report


def test_run_doctor_replay_backend_without_path(monkeypatch) -> None:
    _patch_config_loader(monkeypatch, AppConfig(use_mock_capture=False, prefer_backend="replay", replay_frames_path=""))
    monkeypatch.setattr(doctor, "_check_python_runtime", lambda: DoctorCheck("python", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_dependencies", lambda: DoctorCheck("dependencies", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_session_bus", lambda: DoctorCheck("session-bus", "pass", "ok"))
    async def _probe_pass() -> DoctorCheck:
        return DoctorCheck("kwin-screenshot2", "pass", "ok")

    monkeypatch.setattr(doctor, "_probe_kwin_screenshot2", _probe_pass)
    monkeypatch.setattr(doctor, "_check_desktop_authorization", lambda: DoctorCheck("desktop-authorization", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_hid_enumeration", lambda cfg: DoctorCheck("hid-device", "warn", "skip for replay test"))

    checks = run_doctor()
    report = format_report(checks)
    mode_check = next(check for check in checks if check.name == "mode-consistency")

    assert mode_check.status == "fail"
    assert "replay_frames_path is empty" in mode_check.message
    assert "Set replay_frames_path to a .npz file" in mode_check.action
    assert "FAIL (1)" in report
    assert "replay_frames_path" in report


def test_run_doctor_kwin_authorization_denial_guidance(monkeypatch) -> None:
    _patch_config_loader(monkeypatch, AppConfig())
    monkeypatch.setattr(doctor, "_check_python_runtime", lambda: DoctorCheck("python", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_dependencies", lambda: DoctorCheck("dependencies", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_session_bus", lambda: DoctorCheck("session-bus", "pass", "ok"))
    async def _probe_denied() -> DoctorCheck:
        return DoctorCheck(
            "kwin-screenshot2",
            "warn",
            "ScreenShot2 interface not confirmed: org.freedesktop.DBus.Error.AccessDenied",
            "Re-launch from the authorized desktop file and approve the KWin capture prompt.",
        )

    monkeypatch.setattr(doctor, "_probe_kwin_screenshot2", _probe_denied)
    monkeypatch.setattr(doctor, "_check_desktop_authorization", lambda: DoctorCheck("desktop-authorization", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_hid_enumeration", lambda cfg: DoctorCheck("hid-device", "warn", "mock device"))

    report = format_report(run_doctor())
    assert "WARN (2)" in report
    assert "AccessDenied" in report
    assert "Re-launch from the authorized desktop file" in report


def test_run_probe_sync_works_inside_running_loop(monkeypatch) -> None:
    async def _probe_pass() -> DoctorCheck:
        return DoctorCheck("kwin-screenshot2", "pass", "ok")

    monkeypatch.setattr(doctor, "_probe_kwin_screenshot2", _probe_pass)

    async def _call() -> DoctorCheck:
        return doctor._run_probe_sync()

    result = doctor.asyncio.run(_call())
    assert result.status == "pass"
