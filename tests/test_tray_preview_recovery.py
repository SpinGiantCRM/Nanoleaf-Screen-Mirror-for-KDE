from __future__ import annotations

from types import SimpleNamespace

from nanoleaf_sync.ui.tray_app import NanoleafTrayApp


class _FailingPreviewDriver:
    def initialize(self) -> None:
        raise RuntimeError("preview init failed")

    def close(self) -> None:
        return None


class _FakeService:
    def __init__(self) -> None:
        self._running = True
        self.start_calls = 0
        self.stop_calls = 0

    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        self.start_calls += 1
        self._running = True

    def stop(self) -> None:
        self.stop_calls += 1
        self._running = False


def test_send_calibration_preview_recovers_service_when_preview_driver_acquire_fails() -> None:
    service = _FakeService()
    messages: list[str] = []
    fake_tray = SimpleNamespace(
        service=service,
        _preview_driver=None,
        _preview_paused_service=False,
        _make_preview_driver=lambda: _FailingPreviewDriver(),
        on_stop=lambda: service.stop(),
        tray_icon=SimpleNamespace(showMessage=lambda _title, message, _icon, _ms: messages.append(message)),
        QSystemTrayIcon=SimpleNamespace(MessageIcon=SimpleNamespace(Warning=1)),
    )
    fake_tray._acquire_preview_driver = lambda: NanoleafTrayApp._acquire_preview_driver(fake_tray)
    fake_tray._close_preview_driver = lambda *, resume_service=True: NanoleafTrayApp._close_preview_driver(
        fake_tray,
        resume_service=resume_service,
    )

    NanoleafTrayApp._send_calibration_preview(fake_tray, [(255, 0, 0)])

    assert service.stop_calls == 1
    assert service.start_calls == 1
    assert service.is_running() is True
    assert any("Calibration test pattern failed" in message for message in messages)
