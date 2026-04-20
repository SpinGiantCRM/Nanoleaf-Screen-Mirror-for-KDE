from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.tools import doctor
from nanoleaf_sync.tools.doctor import DoctorCheck, _check_mode_consistency, format_report, run_doctor


def test_mode_consistency_kmsgrab_is_supported() -> None:
    cfg = AppConfig(use_mock_capture=False, prefer_backend="kmsgrab")
    result = _check_mode_consistency(cfg)
    assert result.status == "pass"


def test_mode_consistency_mock_capture_real_device_warns() -> None:
    cfg = AppConfig(use_mock_capture=True)
    result = _check_mode_consistency(cfg)
    assert result.status == "pass"


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


def _patch_config_loader(monkeypatch, cfg: AppConfig) -> None:
    class _FakeConfigManager:
        def load(self) -> AppConfig:
            return cfg

    monkeypatch.setattr(doctor, "ConfigManager", _FakeConfigManager)
    monkeypatch.setattr(doctor, "validate_config", lambda loaded_cfg: loaded_cfg)


def test_run_doctor_real_device_requested_hid_unavailable(monkeypatch) -> None:
    _patch_config_loader(monkeypatch, AppConfig(device_vid=0x37FA, device_pid=0x8201))
    monkeypatch.setattr(doctor, "_check_python_runtime", lambda: DoctorCheck("python", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_dependencies", lambda: DoctorCheck("dependencies", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_session_bus", lambda: DoctorCheck("session-bus", "pass", "ok"))

    async def _probe_pass() -> DoctorCheck:
        return DoctorCheck("kwin-screenshot2", "pass", "ok")

    monkeypatch.setattr(doctor, "_probe_kwin_screenshot2", _probe_pass)
    monkeypatch.setattr(doctor, "_check_desktop_authorization", lambda: DoctorCheck("desktop-authorization", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_real_device_probe", lambda cfg: DoctorCheck("device-probe", "warn", "probe skipped"))

    def _raise_hid_unavailable(*_args, **_kwargs):
        raise RuntimeError("hid backend unavailable")

    monkeypatch.setitem(doctor.sys.modules, "hid", SimpleNamespace(enumerate=_raise_hid_unavailable))

    checks = run_doctor(include_device_probe=True)
    hid_check = next(check for check in checks if check.name == "hid-device")
    assert hid_check.status == "fail"
    assert "hid backend unavailable" in hid_check.message.lower()


def test_run_probe_sync_works_inside_running_loop(monkeypatch) -> None:
    async def _probe_pass() -> DoctorCheck:
        return DoctorCheck("kwin-screenshot2", "pass", "ok")

    monkeypatch.setattr(doctor, "_probe_kwin_screenshot2", _probe_pass)

    async def _call() -> DoctorCheck:
        return doctor._run_probe_sync()

    result = doctor.asyncio.run(_call())
    assert result.status == "pass"


def test_run_doctor_with_capture_probe(monkeypatch) -> None:
    _patch_config_loader(monkeypatch, AppConfig(device_vid=0x37FA, device_pid=0x8201))
    monkeypatch.setattr(doctor, "_check_python_runtime", lambda: DoctorCheck("python", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_dependencies", lambda: DoctorCheck("dependencies", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_session_bus", lambda: DoctorCheck("session-bus", "pass", "ok"))
    monkeypatch.setattr(doctor, "_run_probe_sync", lambda: DoctorCheck("kwin-screenshot2", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_desktop_authorization", lambda: DoctorCheck("desktop-authorization", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_hid_enumeration", lambda cfg: DoctorCheck("hid-device", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_real_capture_probe", lambda cfg: DoctorCheck("capture-probe", "fail", "boom"))

    checks = run_doctor(include_capture_probe=True)
    capture_check = next(check for check in checks if check.name == "capture-probe")
    assert capture_check.status == "fail"

def test_run_doctor_skips_kwin_probe_for_portal_backend(monkeypatch) -> None:
    _patch_config_loader(
        monkeypatch,
        AppConfig(device_vid=0x37FA, device_pid=0x8201, use_mock_capture=False, prefer_backend="portal"),
    )
    monkeypatch.setattr(doctor, "_check_python_runtime", lambda: DoctorCheck("python", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_dependencies", lambda: DoctorCheck("dependencies", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_session_bus", lambda: DoctorCheck("session-bus", "pass", "ok"))
    monkeypatch.setattr(doctor, "_check_hid_enumeration", lambda cfg: DoctorCheck("hid-device", "pass", "ok"))
    monkeypatch.setattr(doctor, "_run_probe_sync", lambda: (_ for _ in ()).throw(AssertionError("kwin probe should be skipped")))

    checks = run_doctor()
    desktop_auth = next(check for check in checks if check.name == "desktop-authorization")
    probe_status = next(check for check in checks if check.name == "probe-status")
    assert desktop_auth.status == "pass"
    assert "not required for xdg-portal" in desktop_auth.message
    assert probe_status.status == "pass"
    assert "Selection reason=explicit" in probe_status.message


def test_desktop_authorization_warns_when_only_installed_entry_exists(monkeypatch, tmp_path: Path) -> None:
    autostart = tmp_path / "home-autostart.desktop"
    installed = tmp_path / "usr" / "share" / "applications" / "nanoleaf-kde-sync.desktop"
    installed.parent.mkdir(parents=True, exist_ok=True)
    installed.write_text(
        f"[Desktop Entry]\n{doctor.RESTRICTED_IFACE_MARKER}\n",
        encoding="utf-8",
    )
    template = tmp_path / "repo-docs.desktop"
    template.write_text(
        f"[Desktop Entry]\n{doctor.RESTRICTED_IFACE_MARKER}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(doctor, "user_autostart_path", lambda: autostart)
    monkeypatch.setattr(doctor, "installed_desktop_entry_candidates", lambda: [installed])
    monkeypatch.setattr(doctor, "source_desktop_template_path", lambda: template)

    result = doctor._check_desktop_authorization()
    assert result.status == "warn"
    assert "autostart is disabled" in result.message.lower()


def test_doctor_help_lists_documented_capture_and_device_flags(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        doctor.main(["--help"])
    assert excinfo.value.code == 0
    help_text = capsys.readouterr().out
    assert "--capture" in help_text
    assert "--device" in help_text
