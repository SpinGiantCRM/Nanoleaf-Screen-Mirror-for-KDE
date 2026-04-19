from __future__ import annotations

from pathlib import Path

from nanoleaf_sync import desktop_entry


def test_enable_autostart_copies_template_and_marker(monkeypatch, tmp_path: Path) -> None:
    template = tmp_path / "nanoleaf-kde-sync.desktop"
    template.write_text("[Desktop Entry]\nName=demo\n", encoding="utf-8")
    autostart = tmp_path / "autostart" / "nanoleaf-kde-sync.desktop"

    monkeypatch.setattr(desktop_entry, "source_desktop_template_path", lambda: template)
    monkeypatch.setattr(desktop_entry, "installed_desktop_entry_candidates", lambda: [])
    monkeypatch.setattr(desktop_entry, "user_autostart_path", lambda: autostart)

    out = desktop_entry.enable_autostart()
    assert out == autostart
    content = autostart.read_text(encoding="utf-8")
    assert desktop_entry.RESTRICTED_IFACE_MARKER in content


def test_disable_autostart_when_missing(monkeypatch, tmp_path: Path) -> None:
    autostart = tmp_path / "autostart" / "nanoleaf-kde-sync.desktop"
    monkeypatch.setattr(desktop_entry, "user_autostart_path", lambda: autostart)
    assert desktop_entry.disable_autostart() is False


def test_launch_context_snapshot_reads_expected_env(monkeypatch) -> None:
    monkeypatch.setenv("DESKTOP_STARTUP_ID", "start-1")
    monkeypatch.setenv("XDG_ACTIVATION_TOKEN", "token-1")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setenv("XDG_SESSION_DESKTOP", "KDE")
    monkeypatch.setenv("KDE_SESSION_VERSION", "6")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/tmp/bus")

    snapshot = desktop_entry.launch_context_snapshot()

    assert snapshot["DESKTOP_STARTUP_ID"] == "start-1"
    assert snapshot["XDG_ACTIVATION_TOKEN"] == "token-1"
    assert snapshot["XDG_CURRENT_DESKTOP"] == "KDE"
    assert snapshot["XDG_SESSION_DESKTOP"] == "KDE"
    assert snapshot["KDE_SESSION_VERSION"] == "6"
    assert snapshot["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/tmp/bus"
