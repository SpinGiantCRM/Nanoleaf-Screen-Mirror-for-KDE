from __future__ import annotations

import json

from nanoleaf_sync.ui import tray_app


def test_self_check_success(monkeypatch, capsys):
    monkeypatch.setattr(tray_app, "SELF_CHECK_IMPORTS", ("json",))
    monkeypatch.setattr(tray_app, "load_qt", lambda: {"QApplication": object()})

    rc = tray_app.main(["--self-check"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "nanoleaf-kde-sync-self-check"
    assert payload["status"] == "ok"
    assert any(check["check"] == "qt:load_qt" for check in payload["checks"])


def test_self_check_failure(monkeypatch, capsys):
    monkeypatch.setattr(tray_app, "SELF_CHECK_IMPORTS", ("json",))

    def _broken_load_qt():
        raise RuntimeError("boom")

    monkeypatch.setattr(tray_app, "load_qt", _broken_load_qt)

    rc = tray_app.main(["--self-check"])

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["error"]["type"] == "RuntimeError"
    assert payload["error"]["message"] == "boom"


def test_reset_probe_cache_cli(monkeypatch, capsys):
    class _FakeManager:
        path = "/tmp/config.toml"

        def reset_auto_probe_cache(self):
            return type(
                "Cfg", (), {"auto_probe_policy": "on-change", "auto_selected_backend": ""}
            )()

    monkeypatch.setattr(tray_app, "ConfigManager", _FakeManager)
    rc = tray_app.main(["--reset-probe-cache"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Reset auto-probe cache in /tmp/config.toml" in out
