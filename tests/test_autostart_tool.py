from __future__ import annotations

from nanoleaf_sync.tools import autostart


def test_autostart_tool_status(monkeypatch, capsys) -> None:
    class _Path:
        def exists(self) -> bool:
            return False

        def __str__(self) -> str:
            return "/tmp/nope.desktop"

    monkeypatch.setattr(autostart, "user_autostart_path", lambda: _Path())
    rc = autostart.main(["status"])
    assert rc == 0
    assert "disabled" in capsys.readouterr().out.lower()


def test_autostart_tool_enable_systemd_prints_authorization_warning(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        autostart, "enable_systemd_autostart", lambda: "/tmp/nanoleaf-kde-sync.service"
    )
    rc = autostart.main(["enable", "--method", "systemd"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Enabled autostart" in out
    assert "WARNING" in out
    assert "--method desktop" in out
