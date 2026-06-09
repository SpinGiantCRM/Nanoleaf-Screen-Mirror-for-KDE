from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.tools import doctor
from nanoleaf_sync.tools.doctor import DoctorCheck, _build_issue_body, _open_upstream_issue


def _sample_checks() -> list[DoctorCheck]:
    return [
        DoctorCheck("python", "pass", "Python 3.12.0 detected."),
        DoctorCheck("dependencies", "pass", "Core Python modules are importable."),
    ]


def _patch_version_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        doctor,
        "collect_current_versions",
        lambda: {
            "last_seen_kwin_version": "6.3.1",
            "last_seen_kde_plasma_version": "6.3.1",
            "last_seen_screenshot2_version": 5,
            "last_seen_portal_version": 6,
            "last_seen_python_version": "3.12.0",
        },
    )
    monkeypatch.setattr(doctor, "get_plasma_version", lambda: (6, 3, 1))
    monkeypatch.setattr(doctor, "get_kwin_version", lambda: (6, 3, 1))
    monkeypatch.setattr(doctor, "get_screenshot2_api_version", lambda: 5)
    monkeypatch.setattr(doctor, "get_portal_version", lambda: 6)
    monkeypatch.setattr(doctor, "supports_pipewire_serial", lambda: True)
    monkeypatch.setattr(doctor, "check_for_upgrade", lambda: {"changed": {}})


def test_build_issue_body_includes_environment_and_reports() -> None:
    env_info = {
        "last_seen_kwin_version": "6.3.1",
        "last_seen_kde_plasma_version": "6.3.1",
        "last_seen_screenshot2_version": 5,
        "last_seen_portal_version": 6,
        "last_seen_python_version": "3.12.0",
    }
    compat_lines = ["KDE Compatibility:", "  KWin version:    6.3.1"]
    report_text = "== nanoleaf-kde-sync doctor ==\nPASS (1)"

    body = _build_issue_body(report_text, env_info, compat_lines)

    assert "## Environment" in body
    assert "| KWin | 6.3.1 |" in body
    assert "| Plasma | 6.3.1 |" in body
    assert "| ScreenShot2 API | v5 |" in body
    assert "| Portal version | 6 |" in body
    assert "| Python | 3.12.0 |" in body
    assert "| Platform |" in body
    assert "## KDE Compatibility" in body
    assert "KDE Compatibility:" in body
    assert "## Doctor Report" in body
    assert "<details>" in body
    assert report_text in body
    assert "## Error Logs" in body
    assert "None captured" in body


def test_open_upstream_issue_builds_github_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_version_probes(monkeypatch)
    opened: list[str] = []
    monkeypatch.setattr(doctor.webbrowser, "open", opened.append)

    url = _open_upstream_issue(_sample_checks())

    assert opened == [url]
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "github.com"
    assert parsed.path == "/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/issues/new"
    params = parse_qs(parsed.query)
    assert "title" in params
    assert "body" in params
    assert params["title"][0] == "Compatibility issue: 6.3.1 / Plasma 6.3.1"
    body = params["body"][0]
    assert "## Environment" in body
    assert "== nanoleaf-kde-sync doctor ==" in body
    assert "KDE Compatibility:" in body


def test_report_upstream_runs_full_doctor_suite(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_version_probes(monkeypatch)
    monkeypatch.setattr(doctor.webbrowser, "open", lambda _url: True)

    class _FakeConfigManager:
        def load(self) -> AppConfig:
            return AppConfig(device_vid=0x37FA, device_pid=0x8201)

    monkeypatch.setattr(doctor, "ConfigManager", _FakeConfigManager)
    monkeypatch.setattr(doctor, "validate_config", lambda cfg: cfg)

    run_kwargs: list[dict[str, bool]] = []

    def _record_run_doctor(**kwargs: bool) -> list[DoctorCheck]:
        run_kwargs.append(kwargs)
        return _sample_checks()

    monkeypatch.setattr(doctor, "run_doctor", _record_run_doctor)

    exit_code = doctor.main(["--report-upstream"])

    assert run_kwargs == [{"include_device_probe": True, "include_capture_probe": True}]
    assert exit_code == 0


def test_doctor_help_lists_report_upstream_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        doctor.main(["--help"])
    assert excinfo.value.code == 0
    help_text = capsys.readouterr().out
    assert "--report-upstream" in help_text
