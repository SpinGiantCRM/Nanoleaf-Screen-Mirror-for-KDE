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
    class _CfgMgr:
        def load(self):
            return AppConfig(device_vid=0, device_pid=0)

    monkeypatch.setattr(smoke_test, "ConfigManager", _CfgMgr)
    monkeypatch.setattr(smoke_test, "create_capture_backend", lambda **_kwargs: _CaptureStub())

    exit_code = smoke_test.main([])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "VID/PID not configured" in out
