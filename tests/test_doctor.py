from __future__ import annotations

from types import SimpleNamespace

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.tools import doctor
from nanoleaf_sync.tools.doctor import DoctorCheck, _check_mode_consistency, format_report, run_doctor


def test_mode_consistency_unsupported_backend_fails() -> None:
    cfg = AppConfig(use_mock_capture=False, prefer_backend="kmsgrab")
    result = _check_mode_consistency(cfg)
    assert result.status == "fail"
    assert "Unsupported real capture backend" in result.message


def test_mode_consistency_mock_capture_real_device_warns() -> None:
    cfg = AppConfig(use_mock_capture=True, use_mock_device=False)
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


def _patch_config_loader(monkeypatch, cfg: AppConfig) -> None:
    class _FakeConfigManager:
        def load(self) -> AppConfig:
            return cfg

    monkeypatch.setattr(doctor, "ConfigManager", _FakeConfigManager)
    monkeypatch.setattr(doctor, "validate_config", lambda loaded_cfg: loaded_cfg)


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

    def _raise_hid_unavailable(*_args, **_kwargs):
        raise RuntimeError("hid backend unavailable")

    monkeypatch.setitem(doctor.sys.modules, "hid", SimpleNamespace(enumerate=_raise_hid_unavailable))

    checks = run_doctor(include_device_probe=True)
    hid_check = next(check for check in checks if check.name == "hid-device")
    assert hid_check.status == "fail"


def test_run_probe_sync_works_inside_running_loop(monkeypatch) -> None:
    async def _probe_pass() -> DoctorCheck:
        return DoctorCheck("kwin-screenshot2", "pass", "ok")

    monkeypatch.setattr(doctor, "_probe_kwin_screenshot2", _probe_pass)

    async def _call() -> DoctorCheck:
        return doctor._run_probe_sync()

    result = doctor.asyncio.run(_call())
    assert result.status == "pass"
