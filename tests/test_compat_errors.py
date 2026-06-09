from __future__ import annotations

from nanoleaf_sync.runtime.errors import translate_runtime_error


def test_kwin_authorization_includes_kde_context(monkeypatch) -> None:
    monkeypatch.setattr(
        "nanoleaf_sync.compat.kde_version.get_kwin_version",
        lambda: (6, 4, 0),
    )
    monkeypatch.setattr(
        "nanoleaf_sync.compat.kde_version.get_plasma_version",
        lambda: (6, 4, 0),
    )
    monkeypatch.setattr(
        "nanoleaf_sync.compat.kwin_probe.get_screenshot2_api_version",
        lambda: 5,
    )
    monkeypatch.setattr(
        "nanoleaf_sync.compat.portal_probe.get_portal_version",
        lambda: 6,
    )

    result = translate_runtime_error(RuntimeError("Screen access denied: NotAuthorized"))
    assert result.kind == "kwin-authorization"
    assert "KDE Plasma 6.4.0" in result.guidance
    assert "TROUBLESHOOTING.md" in result.guidance


def test_portal_failure_includes_version_hint_for_new_portal(monkeypatch) -> None:
    monkeypatch.setattr(
        "nanoleaf_sync.compat.portal_probe.get_portal_version",
        lambda: 7,
    )
    monkeypatch.setattr(
        "nanoleaf_sync.compat.kde_version.get_kwin_version",
        lambda: (6, 3, 1),
    )
    monkeypatch.setattr(
        "nanoleaf_sync.compat.kde_version.get_plasma_version",
        lambda: (6, 3, 1),
    )
    monkeypatch.setattr(
        "nanoleaf_sync.compat.kwin_probe.get_screenshot2_api_version",
        lambda: 5,
    )

    result = translate_runtime_error(RuntimeError("portal negotiation failed"))
    assert result.kind == "portal-backend"
    assert "kwin-dbus backend" in result.guidance
