"""Tests for desktop_entry.py uncovered paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanoleaf_sync import desktop_entry


def test_project_root() -> None:
    root = desktop_entry.project_root()
    assert root.is_dir()
    assert (root / "src").is_dir()


def test_source_desktop_template_path() -> None:
    path = desktop_entry.source_desktop_template_path()
    assert path.name == desktop_entry.AUTOSTART_DESKTOP_NAME


def test_xdg_data_home_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", "/custom/data")
    result = desktop_entry._xdg_data_home()
    assert result == Path("/custom/data")


def test_xdg_data_home_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    result = desktop_entry._xdg_data_home()
    assert result == Path.home() / ".local" / "share"


def test_user_autostart_path() -> None:
    path = desktop_entry.user_autostart_path()
    assert path.name == desktop_entry.AUTOSTART_DESKTOP_NAME
    assert ".config/autostart" in str(path)


def test_user_systemd_service_path() -> None:
    path = desktop_entry.user_systemd_service_path()
    assert path.name == desktop_entry.SYSTEMD_SERVICE_NAME
    assert ".config/systemd/user" in str(path)


def test_installed_desktop_entry_candidates_with_xdg_data_dirs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_DATA_DIRS", "/usr/share:/usr/local/share")
    candidates = desktop_entry.installed_desktop_entry_candidates()
    assert len(candidates) >= 2


def test_installed_desktop_entry_candidates_default() -> None:
    candidates = desktop_entry.installed_desktop_entry_candidates()
    # At minimum includes the XDG_DATA_HOME path
    assert len(candidates) >= 1
    # All are unique
    assert len(candidates) == len(set(candidates))


def test_desktop_entry_has_restricted_marker_true(tmp_path: Path) -> None:
    path = tmp_path / "test.desktop"
    path.write_text("[Desktop Entry]\nX-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2\n")
    assert desktop_entry.desktop_entry_has_restricted_marker(path) is True


def test_desktop_entry_has_restricted_marker_false(tmp_path: Path) -> None:
    path = tmp_path / "test.desktop"
    path.write_text("[Desktop Entry]\nExec=foo\n")
    assert desktop_entry.desktop_entry_has_restricted_marker(path) is False


def test_desktop_entry_has_restricted_marker_no_file() -> None:
    path = Path("/nonexistent/desktop/file.desktop")
    assert desktop_entry.desktop_entry_has_restricted_marker(path) is False


def test_launch_context_snapshot() -> None:
    snap = desktop_entry.launch_context_snapshot()
    assert isinstance(snap, dict)
    assert "XDG_CURRENT_DESKTOP" in snap
    assert "DBUS_SESSION_BUS_ADDRESS" in snap


def test_preferred_user_desktop_entry_path() -> None:
    path = desktop_entry.preferred_user_desktop_entry_path()
    assert path.name == desktop_entry.AUTOSTART_DESKTOP_NAME
    assert "applications" in str(path)


def test_runtime_exec_command_normal() -> None:
    cmd = desktop_entry.runtime_exec_command()
    assert "nanoleaf_sync" in cmd or "python" in cmd.lower()


def test_upsert_desktop_key_no_section_header() -> None:
    text = "Exec=/usr/bin/app"
    result = desktop_entry._upsert_desktop_key(text, "Name", "My App")
    assert "[Desktop Entry]" in result
    assert "Name=My App" in result


def test_upsert_desktop_key_existing_key() -> None:
    text = "[Desktop Entry]\nExec=/usr/bin/app"
    result = desktop_entry._upsert_desktop_key(text, "Exec", "/usr/bin/newapp")
    assert "Exec=/usr/bin/newapp" in result
    assert "Exec=/usr/bin/app" not in result


def test_upsert_desktop_key_new_key() -> None:
    text = "[Desktop Entry]\nExec=/usr/bin/app"
    result = desktop_entry._upsert_desktop_key(text, "Name", "My App")
    assert "Name=My App" in result
    lines_after_desktop = result.split("[Desktop Entry]")[1]
    assert "Name=My App" in lines_after_desktop


def test_prepare_desktop_entry_text_adds_header() -> None:
    text = "Exec=test"
    result = desktop_entry._prepare_desktop_entry_text(text)
    assert result.startswith("[Desktop Entry]")
    assert "Exec=test" in result


def test_prepare_desktop_entry_text_adds_restricted_marker() -> None:
    text = "[Desktop Entry]\nExec=test"
    result = desktop_entry._prepare_desktop_entry_text(text)
    assert desktop_entry.RESTRICTED_IFACE_MARKER in result


def test_prepare_desktop_entry_text_with_exec_command() -> None:
    text = "[Desktop Entry]\nExec=old"
    result = desktop_entry._prepare_desktop_entry_text(text, exec_command="new-exec")
    assert "Exec=new-exec" in result
    assert "Exec=old" not in result


def test_ensure_user_launcher_entry_from_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When source template exists, use it."""
    monkeypatch.setattr(
        desktop_entry,
        "preferred_user_desktop_entry_path",
        lambda: tmp_path / "nanoleaf-kde-sync.desktop",
    )
    monkeypatch.setattr(desktop_entry, "_resolved_desktop_source", lambda: None)
    monkeypatch.setattr(desktop_entry, "runtime_exec_command", lambda: "python -m nanoleaf_sync")

    path = desktop_entry.ensure_user_launcher_entry()
    assert path.exists()
    content = path.read_text()
    assert "[Desktop Entry]" in content
    assert "Type=Application" in content


def test_ensure_user_launcher_entry_self_heals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no source template, self-heals with minimal entry."""
    monkeypatch.setattr(
        desktop_entry,
        "preferred_user_desktop_entry_path",
        lambda: tmp_path / "nanoleaf-kde-sync.desktop",
    )
    monkeypatch.setattr(desktop_entry, "_resolved_desktop_source", lambda: None)
    monkeypatch.setattr(desktop_entry, "runtime_exec_command", lambda: "python -m nanoleaf_sync")

    path = desktop_entry.ensure_user_launcher_entry()
    assert path.exists()
    content = path.read_text()
    assert "[Desktop Entry]" in content
    assert desktop_entry.RESTRICTED_IFACE_MARKER in content


def test_redact_launch_token_unset() -> None:
    assert desktop_entry.redact_launch_token(None) == "unset"
    assert desktop_entry.redact_launch_token("") == "unset"


def test_redact_launch_token_short() -> None:
    assert desktop_entry.redact_launch_token("abc") == "***"


def test_redact_launch_token_long() -> None:
    result = desktop_entry.redact_launch_token("abcdefghijk")
    assert "…" in result
    assert len(result) <= 10


def test_resolved_desktop_source_template_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template = tmp_path / "nanoleaf-kde-sync.desktop"
    template.write_text("[Desktop Entry]\nExec=test")
    monkeypatch.setattr(desktop_entry, "source_desktop_template_path", lambda: template)
    monkeypatch.setattr(desktop_entry, "installed_desktop_entry_candidates", lambda: [])
    result = desktop_entry._resolved_desktop_source()
    assert result == template


def test_resolved_desktop_source_from_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template = tmp_path / "nonexistent.desktop"
    installed = tmp_path / "installed.desktop"
    installed.write_text("[Desktop Entry]")
    monkeypatch.setattr(desktop_entry, "source_desktop_template_path", lambda: template)
    monkeypatch.setattr(desktop_entry, "installed_desktop_entry_candidates", lambda: [installed])
    result = desktop_entry._resolved_desktop_source()
    assert result == installed


def test_resolved_desktop_source_none_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        desktop_entry, "source_desktop_template_path", lambda: tmp_path / "nonexistent"
    )
    monkeypatch.setattr(desktop_entry, "installed_desktop_entry_candidates", lambda: [])
    result = desktop_entry._resolved_desktop_source()
    assert result is None


def test_disable_autostart_not_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        desktop_entry, "user_autostart_path", lambda: tmp_path / "nonexistent.desktop"
    )
    result = desktop_entry.disable_autostart()
    assert result is False


def test_disable_autostart_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "autostart.desktop"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[Desktop Entry]")
    monkeypatch.setattr(desktop_entry, "user_autostart_path", lambda: path)
    result = desktop_entry.disable_autostart()
    assert result is True
    assert not path.exists()
