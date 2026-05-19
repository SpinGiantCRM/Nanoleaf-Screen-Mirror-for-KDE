from __future__ import annotations

from types import SimpleNamespace

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.output_session import OutputSessionController
from nanoleaf_sync.ui.tray_app import NanoleafTrayApp


class _FailingPreviewDriver:
    def initialize(self) -> None:
        raise RuntimeError("preview init failed")

    def close(self) -> None:
        return None


class _FakeService:
    def __init__(self, config: AppConfig | None = None, *, detected_zone_count: int = 48) -> None:
        self._running = True
        self.start_calls = 0
        self.stop_calls = 0
        self.config = config or AppConfig(device_zone_count=8)
        self._status = {
            "device_zone_count": detected_zone_count,
            "detected_device_zone_count": detected_zone_count,
        }

    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        self.start_calls += 1
        self._running = True

    def stop(self) -> None:
        self.stop_calls += 1
        self._running = False

    def get_status(self) -> dict[str, int]:
        return dict(self._status)

    def join(self, timeout: float | None = None) -> None:
        _ = timeout


class _FakeCfgMgr:
    def __init__(self) -> None:
        self.saved: AppConfig | None = None

    def save(self, config: AppConfig) -> None:
        self.saved = config


def _fake_tray(service: _FakeService, *, messages: list[str], make_driver):
    cfg_mgr = _FakeCfgMgr()
    cfg = service.config
    cfg.calibration.device_zone_count = int(
        getattr(cfg, "calibration", None).device_zone_count or cfg.device_zone_count
    )
    tray = SimpleNamespace(
        service=service,
        config=cfg,
        cfg_mgr=cfg_mgr,
        _preview_driver=None,
        _preview_paused_service=False,
        _output_session=OutputSessionController(),
        _make_preview_driver=make_driver,
        on_stop=lambda: service.stop(),
        tray_icon=SimpleNamespace(
            showMessage=lambda _title, message, _icon, _ms: messages.append(message)
        ),
        QSystemTrayIcon=SimpleNamespace(MessageIcon=SimpleNamespace(Warning=1)),
    )
    tray._build_calibration_preview_diagnostics = lambda *, frame_color_count, driver=None: (
        NanoleafTrayApp._build_calibration_preview_diagnostics(
            tray,
            frame_color_count=frame_color_count,
            driver=driver,
        )
    )
    tray._reconcile_calibration_preview_zone_config = lambda *, diagnostics: (
        NanoleafTrayApp._reconcile_calibration_preview_zone_config(
            tray,
            diagnostics=diagnostics,
        )
    )
    return tray


def test_send_calibration_preview_recovers_service_when_preview_driver_acquire_fails() -> None:
    service = _FakeService()
    messages: list[str] = []
    fake_tray = _fake_tray(service, messages=messages, make_driver=lambda: _FailingPreviewDriver())
    fake_tray._acquire_preview_driver = lambda: NanoleafTrayApp._acquire_preview_driver(fake_tray)
    fake_tray._close_preview_driver = lambda *, resume_service=True: (
        NanoleafTrayApp._close_preview_driver(
            fake_tray,
            resume_service=resume_service,
        )
    )

    NanoleafTrayApp._send_calibration_preview(fake_tray, [(255, 0, 0)])

    assert service.stop_calls == 2
    assert service.start_calls == 2
    assert service.is_running() is True
    assert any("Calibration test pattern failed" in message for message in messages)


class _FlakyPreviewDriver:
    def __init__(self, should_fail: bool) -> None:
        self.should_fail = should_fail

    def initialize(self) -> None:
        return None

    def send_frame(self, _colors) -> None:
        if self.should_fail:
            raise RuntimeError("read error")

    def close(self) -> None:
        return None


def test_send_calibration_preview_retries_once_before_notifying_failure() -> None:
    service = _FakeService()
    messages: list[str] = []
    attempts = {"count": 0}

    def make_driver():
        attempts["count"] += 1
        return _FlakyPreviewDriver(should_fail=attempts["count"] == 1)

    fake_tray = _fake_tray(service, messages=messages, make_driver=make_driver)
    fake_tray._acquire_preview_driver = lambda: NanoleafTrayApp._acquire_preview_driver(fake_tray)
    fake_tray._close_preview_driver = lambda *, resume_service=True: (
        NanoleafTrayApp._close_preview_driver(
            fake_tray,
            resume_service=resume_service,
        )
    )

    NanoleafTrayApp._send_calibration_preview(fake_tray, [(255, 0, 0)])

    assert attempts["count"] == 2
    assert messages == []


def test_send_calibration_preview_notifies_after_retry_exhausted() -> None:
    service = _FakeService()
    messages: list[str] = []

    fake_tray = _fake_tray(
        service, messages=messages, make_driver=lambda: _FlakyPreviewDriver(should_fail=True)
    )
    fake_tray._acquire_preview_driver = lambda: NanoleafTrayApp._acquire_preview_driver(fake_tray)
    fake_tray._close_preview_driver = lambda *, resume_service=True: (
        NanoleafTrayApp._close_preview_driver(
            fake_tray,
            resume_service=resume_service,
        )
    )

    NanoleafTrayApp._send_calibration_preview(fake_tray, [(255, 0, 0)])

    assert any("Calibration test pattern failed: read error" in message for message in messages)


def test_send_calibration_preview_never_promotes_manual_zone_count_from_detected() -> None:
    cfg = AppConfig(device_zone_count=8)
    cfg.calibration.device_zone_count = 8
    service = _FakeService(config=cfg, detected_zone_count=48)
    messages: list[str] = []

    fake_tray = _fake_tray(
        service, messages=messages, make_driver=lambda: _FlakyPreviewDriver(should_fail=False)
    )
    fake_tray._acquire_preview_driver = lambda: NanoleafTrayApp._acquire_preview_driver(fake_tray)
    fake_tray._close_preview_driver = lambda *, resume_service=True: (
        NanoleafTrayApp._close_preview_driver(
            fake_tray,
            resume_service=resume_service,
        )
    )

    NanoleafTrayApp._send_calibration_preview(fake_tray, [(255, 0, 0)] * 48)

    assert fake_tray.config.device_zone_count == 8
    assert fake_tray.config.calibration.device_zone_count == 8
    assert service.config.device_zone_count == 8
    assert service.config.calibration.device_zone_count == 8
    assert fake_tray.cfg_mgr.saved is None
    assert any("synced_device_zone_count=8" in message for message in messages)


def test_make_preview_driver_disables_live_write_optimization_for_setup_paths() -> None:
    captured: dict[str, bool] = {}

    class _Service:
        def _make_device_driver(self, *, enable_live_frame_write_optimization: bool = True):
            captured["enable_live_frame_write_optimization"] = bool(
                enable_live_frame_write_optimization
            )
            return object()

    tray = SimpleNamespace(service=_Service())

    NanoleafTrayApp._make_preview_driver(tray)

    assert captured["enable_live_frame_write_optimization"] is False
