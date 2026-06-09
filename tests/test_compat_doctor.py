from __future__ import annotations

from nanoleaf_sync.tools import doctor


def test_doctor_report_includes_kde_compatibility_section(monkeypatch) -> None:
    monkeypatch.setattr(doctor, "get_plasma_version", lambda: (6, 3, 1))
    monkeypatch.setattr(doctor, "get_kwin_version", lambda: (6, 3, 1))
    monkeypatch.setattr(doctor, "get_screenshot2_api_version", lambda: 5)
    monkeypatch.setattr(doctor, "get_portal_version", lambda: 6)
    monkeypatch.setattr(doctor, "supports_pipewire_serial", lambda: True)
    monkeypatch.setattr(doctor, "check_for_upgrade", lambda: {"changed": {}})

    report = doctor.format_report([])
    assert "KDE Compatibility:" in report
    assert "ScreenShot2 API: v5" in report
    assert "Portal version:  6" in report
