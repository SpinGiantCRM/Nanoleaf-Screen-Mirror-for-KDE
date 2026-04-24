from __future__ import annotations

from nanoleaf_sync.tools import reset as reset_tool


class _FakeConfigManager:
    def __init__(self) -> None:
        self.path = "/tmp/config.toml"
        self.called: str | None = None

    def reset_all_config(self):
        self.called = "app-config"
        return type("Cfg", (), {"device_zone_count": 0})()

    def reset_calibration_only(self):
        self.called = "calibration"
        return type(
            "Cfg",
            (),
            {
                "corner_anchor_top_left": -1,
                "corner_anchor_top_right": -1,
                "corner_anchor_bottom_right": -1,
                "corner_anchor_bottom_left": -1,
            },
        )()

    def reset_diagnostics_cache_only(self):
        self.called = "diagnostics"
        return type("Cfg", (), {"auto_selected_backend": ""})()


def test_reset_tool_scoped_resets(monkeypatch, capsys) -> None:
    fake = _FakeConfigManager()
    monkeypatch.setattr(reset_tool, "ConfigManager", lambda: fake)

    rc = reset_tool.main(["app-config"])
    assert rc == 0
    assert fake.called == "app-config"
    assert "Reset full app config" in capsys.readouterr().out

    rc = reset_tool.main(["calibration"])
    assert rc == 0
    assert fake.called == "calibration"
    assert "Reset calibration only" in capsys.readouterr().out

    rc = reset_tool.main(["diagnostics"])
    assert rc == 0
    assert fake.called == "diagnostics"
    assert "Reset diagnostics/cache only" in capsys.readouterr().out


def test_reset_tool_stop_runtime_calls_pkill(monkeypatch) -> None:
    calls: list[list[str]] = []

    def _fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return None

    monkeypatch.setattr(reset_tool.subprocess, "run", _fake_run)
    monkeypatch.setattr(reset_tool, "ConfigManager", _FakeConfigManager)

    reset_tool.main(["diagnostics", "--stop-runtime"])
    assert calls == [["pkill", "-f", "nanoleaf-kde-sync-service$"], ["pkill", "-f", "nanoleaf-kde-sync$"]]
