from __future__ import annotations

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
