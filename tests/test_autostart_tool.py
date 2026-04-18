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
