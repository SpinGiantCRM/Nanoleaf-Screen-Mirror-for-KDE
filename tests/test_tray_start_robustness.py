from __future__ import annotations

from types import SimpleNamespace

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.tray_app import NanoleafTrayApp


class _FakeServiceRaises:
    last_error = None

    def __init__(self) -> None:
        self.start_calls = 0

    def start(self) -> bool:
        self.start_calls += 1
        raise RuntimeError("boom")

    def is_running(self) -> bool:
        return False

    def get_status(self) -> dict:
        return {}


class _FakeServiceFailedStart:
    def __init__(self) -> None:
        self.last_error = "device open failed"

    def start(self) -> bool:
        return False

    def is_running(self) -> bool:
        return False

    def get_status(self) -> dict:
        return {"last_error_guidance": "check usb permissions"}


def _tray_shell(service) -> SimpleNamespace:
    messages: list[str] = []
    icon_updates: list[str] = []
    fake_icon = SimpleNamespace(
        setIcon=lambda icon: icon_updates.append(str(icon)),
        showMessage=lambda _title, text, _icon, _ms: messages.append(text),
    )
    return SimpleNamespace(
        service=service,
        config=AppConfig(),
        tray_icon=fake_icon,
        _idle_icon="idle",
        _running_icon="running",
        _refresh_mode_labels=lambda: None,
        QSystemTrayIcon=SimpleNamespace(MessageIcon=SimpleNamespace(Warning=1)),
        _messages=messages,
        _icon_updates=icon_updates,
    )


def test_on_start_catches_service_exceptions_and_keeps_tray_alive(monkeypatch) -> None:
    recreated = {"count": 0}

    def _factory(*, config):
        recreated["count"] += 1
        return _FakeServiceFailedStart()

    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.NanoleafSyncService", _factory)
    fake_tray = _tray_shell(_FakeServiceRaises())

    NanoleafTrayApp.on_start(fake_tray)

    assert recreated["count"] == 1
    assert fake_tray.service is not None
    assert any("Start failed with exception" in message for message in fake_tray._messages)
    assert fake_tray._icon_updates[-1] == "idle"


def test_on_start_failed_result_reports_error_without_quitting() -> None:
    fake_tray = _tray_shell(_FakeServiceFailedStart())

    NanoleafTrayApp.on_start(fake_tray)

    assert any("Start failed: device open failed" in message for message in fake_tray._messages)
    assert fake_tray._icon_updates[-1] == "idle"
