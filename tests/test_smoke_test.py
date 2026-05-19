from __future__ import annotations

import pytest

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.tools import smoke_test


class _CaptureStub:
    name = "kwin-dbus"

    def capture(self):
        return type("Frame", (), {"shape": (10, 10, 3)})()

    def close(self):
        return None


def test_smoke_test_rejects_unconfigured_vid_pid(monkeypatch, capsys) -> None:
    calls = {"create_capture_backend": 0}

    class _CfgMgr:
        def load(self):
            return AppConfig(device_vid=0, device_pid=0)

    monkeypatch.setattr(smoke_test, "ConfigManager", _CfgMgr)

    def _capture_factory(**_kwargs):
        calls["create_capture_backend"] += 1
        return _CaptureStub()

    monkeypatch.setattr(smoke_test, "create_capture_backend", _capture_factory)

    exit_code = smoke_test.main([])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "VID/PID not configured" in out
    assert calls["create_capture_backend"] == 0


def test_smoke_test_forwards_auto_probe_kwargs(monkeypatch, capsys) -> None:
    captured_kwargs = {}

    class _CfgMgr:
        def load(self):
            return AppConfig(
                prefer_backend="auto",
                auto_probe_enabled=False,
                auto_selected_backend="xdg-portal",
                device_vid=0x37FA,
                device_pid=0x8202,
            )

    class _DriverStub:
        model_number = "stub-model"
        zone_count = 8

        def initialize(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(smoke_test, "ConfigManager", _CfgMgr)

    def _capture_factory(**kwargs):
        captured_kwargs.update(kwargs)
        return _CaptureStub()

    monkeypatch.setattr(smoke_test, "create_capture_backend", _capture_factory)
    monkeypatch.setattr(smoke_test, "NanoleafUSBDriver", lambda ids: _DriverStub())

    exit_code = smoke_test.main([])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert captured_kwargs["auto_probe_enabled"] is False
    assert captured_kwargs["cached_probe_winner"] == "xdg-portal"
    assert "selection_reason=fresh-probe" in out
    assert "zone-count diagnostics:" in out


def test_smoke_test_prints_kwin_auth_context_for_shell_launch(monkeypatch, capsys) -> None:
    class _CfgMgr:
        def load(self):
            return AppConfig(device_vid=0x37FA, device_pid=0x8202, prefer_backend="kwin-dbus")

    class _CaptureFail:
        name = "kwin-dbus"

        def capture(self):
            raise RuntimeError("denied")

        def close(self):
            return None

    monkeypatch.setattr(smoke_test, "ConfigManager", _CfgMgr)
    monkeypatch.setattr(smoke_test, "create_capture_backend", lambda **_kwargs: _CaptureFail())
    monkeypatch.setattr(
        smoke_test,
        "translate_runtime_error",
        lambda _exc: type(
            "Translated",
            (),
            {"kind": "kwin-authorization", "summary": "auth", "guidance": "launch differently"},
        )(),
    )
    monkeypatch.delenv("DESKTOP_STARTUP_ID", raising=False)
    monkeypatch.delenv("XDG_ACTIVATION_TOKEN", raising=False)

    exit_code = smoke_test.main([])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "context warning: shell-run smoke tests may lack KDE launcher policy" in out
    assert "DESKTOP_STARTUP_ID=unset" in out
    assert "XDG_ACTIVATION_TOKEN=unset" in out
