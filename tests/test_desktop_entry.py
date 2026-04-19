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
    monkeypatch.setattr(desktop_entry, "runtime_exec_command", lambda: "/opt/demo/python -m demo")

    out = desktop_entry.enable_autostart()
    assert out == autostart
    content = autostart.read_text(encoding="utf-8")
    assert desktop_entry.RESTRICTED_IFACE_MARKER in content
    assert "Exec=/opt/demo/python -m demo" in content


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


def test_redact_launch_token_masks_sensitive_values() -> None:
    assert desktop_entry.redact_launch_token(None) == "unset"
    assert desktop_entry.redact_launch_token("   ") == "unset"
    assert desktop_entry.redact_launch_token("abcd1234") == "***"
    assert desktop_entry.redact_launch_token("abcdefghijkl") == "abcd…ijkl"


def test_prepare_desktop_entry_sets_exec_and_marker() -> None:
    text = "[Desktop Entry]\nType=Application\nExec=old-command\n"

    prepared = desktop_entry._prepare_desktop_entry_text(
        text, exec_command="/usr/bin/python3 -m nanoleaf_sync.ui.tray"
    )

    assert "Exec=/usr/bin/python3 -m nanoleaf_sync.ui.tray" in prepared
    assert desktop_entry.RESTRICTED_IFACE_MARKER in prepared


def test_ensure_user_launcher_entry_writes_preferred_path(monkeypatch, tmp_path: Path) -> None:
    template = tmp_path / "template.desktop"
    template.write_text("[Desktop Entry]\nType=Application\nName=Demo\n", encoding="utf-8")
    output_path = tmp_path / "applications" / "nanoleaf-kde-sync.desktop"

    monkeypatch.setattr(desktop_entry, "_resolved_desktop_source", lambda: template)
    monkeypatch.setattr(desktop_entry, "preferred_user_desktop_entry_path", lambda: output_path)

    written = desktop_entry.ensure_user_launcher_entry(exec_command="/abs/python -m app")
    assert written == output_path
    content = output_path.read_text(encoding="utf-8")
    assert "Exec=/abs/python -m app" in content
    assert desktop_entry.RESTRICTED_IFACE_MARKER in content


def test_ensure_user_launcher_entry_generates_default_when_no_source(monkeypatch, tmp_path: Path) -> None:
    output_path = tmp_path / "applications" / "nanoleaf-kde-sync.desktop"

    monkeypatch.setattr(desktop_entry, "_resolved_desktop_source", lambda: None)
    monkeypatch.setattr(desktop_entry, "preferred_user_desktop_entry_path", lambda: output_path)

    written = desktop_entry.ensure_user_launcher_entry(exec_command="/abs/python -m app")
    assert written == output_path
    content = output_path.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in content
    assert "Type=Application" in content
    assert "Exec=/abs/python -m app" in content
    assert desktop_entry.RESTRICTED_IFACE_MARKER in content


def test_prepare_desktop_entry_updates_exec_only_in_main_section() -> None:
    text = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Demo\n"
        "[Desktop Action NewWindow]\n"
        "Exec=old-action-command\n"
    )

    prepared = desktop_entry._prepare_desktop_entry_text(text, exec_command="/usr/bin/python3 -m app")

    assert "Exec=/usr/bin/python3 -m app" in prepared
    assert "Exec=old-action-command" in prepared
