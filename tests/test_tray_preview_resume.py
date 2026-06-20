from __future__ import annotations

from types import SimpleNamespace

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.tray_app import NanoleafTrayApp


class _FakeService:
    instances: list[_FakeService] = []

    def __init__(self, *, config: AppConfig, running: bool = False) -> None:
        self.config = config
        self._running = running
        _FakeService.instances.append(self)

    def is_running(self) -> bool:
        return self._running

    def start(self) -> bool:
        self._running = True
        return True

    def stop(self) -> bool:
        self._running = False
        return True

    def get_status(self) -> dict:
        return {}


class _BlackFrameDriver:
    def __init__(self) -> None:
        self.sent: list[list[tuple[int, int, int]]] = []
        self.closed = False
        self.zone_count = 4

    def send_frame(self, colors: list[tuple[int, int, int]]) -> None:
        self.sent.append(list(colors))

    def close(self) -> None:
        self.closed = True


def test_close_preview_sends_black_frame_before_release() -> None:
    driver = _BlackFrameDriver()
    fake_tray = SimpleNamespace(
        _preview_driver=driver,
        _preview_paused_service=False,
        _preview_pause_notified=False,
        _output_session=SimpleNamespace(release=lambda _owner: None),
        config=AppConfig(device_zone_count=4),
    )

    was_paused = NanoleafTrayApp._close_preview_driver(fake_tray)

    assert was_paused is False
    assert driver.sent == [[(0, 0, 0)] * 4]
    assert driver.closed is True
    assert fake_tray._preview_driver is None


def test_restart_mirroring_service_replaces_service_instance(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.NanoleafSyncService", _FakeService)
    _FakeService.instances.clear()
    original = _FakeService(config=AppConfig(device_zone_count=4), running=True)
    _FakeService.instances.clear()
    fake_tray = SimpleNamespace(
        config=AppConfig(device_zone_count=4),
        service=original,
        tray_icon=SimpleNamespace(showMessage=lambda *_a, **_k: None),
        QSystemTrayIcon=SimpleNamespace(MessageIcon=SimpleNamespace(Warning=1)),
        _refresh_mode_labels=lambda: None,
        on_stop=lambda: fake_tray.service.stop(),
        on_start=lambda: fake_tray.service.start(),
    )

    NanoleafTrayApp._restart_mirroring_service(fake_tray, was_running=True)

    assert len(_FakeService.instances) == 1
    assert fake_tray.service is _FakeService.instances[0]
    assert fake_tray.service is not original
    assert fake_tray.service.is_running() is True
