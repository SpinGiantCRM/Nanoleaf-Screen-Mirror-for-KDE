from __future__ import annotations

from types import SimpleNamespace

from nanoleaf_sync.ui.tray_app import NanoleafTrayApp


class _FakeService:
    def __init__(self) -> None:
        self.stop_calls = 0
        self._running = True

    def stop(self) -> None:
        self.stop_calls += 1

    def is_running(self) -> bool:
        return self._running


class _FakeTimer:
    def __init__(self) -> None:
        self.pending: list[tuple[int, object]] = []

    def singleShot(self, delay_ms: int, callback) -> None:
        self.pending.append((delay_ms, callback))


def test_on_quit_is_non_blocking_and_idempotent() -> None:
    service = _FakeService()
    timer = _FakeTimer()
    quit_calls: list[str] = []
    icons: list[str] = []

    fake_tray = SimpleNamespace(
        service=service,
        QTimer=timer,
        app=SimpleNamespace(quit=lambda: quit_calls.append("quit")),
        tray_icon=SimpleNamespace(setIcon=lambda icon: icons.append(icon)),
        _idle_icon="idle",
        _refresh_mode_labels=lambda: None,
        _shutdown_in_progress=False,
        _shutdown_deadline=0.0,
        _shutdown_poll_interval_s=0.05,
        _shutdown_timeout_s=1.5,
        _quit_finalized=False,
        _close_preview_driver=lambda *, resume_service=False: None,
    )
    fake_tray._request_stop = lambda: NanoleafTrayApp._request_stop(fake_tray)
    fake_tray._set_idle_ui_state = lambda: NanoleafTrayApp._set_idle_ui_state(fake_tray)
    fake_tray._poll_shutdown_completion = lambda: NanoleafTrayApp._poll_shutdown_completion(fake_tray)
    fake_tray._finalize_quit = lambda: NanoleafTrayApp._finalize_quit(fake_tray)

    NanoleafTrayApp.on_quit(fake_tray)

    assert service.stop_calls == 1
    assert quit_calls == []
    assert icons == ["idle"]
    assert len(timer.pending) == 1

    NanoleafTrayApp.on_quit(fake_tray)
    assert service.stop_calls == 1

    _delay, callback = timer.pending.pop(0)
    callback()
    assert quit_calls == []
    assert len(timer.pending) == 1

    service._running = False
    _delay, callback = timer.pending.pop(0)
    callback()

    assert quit_calls == ["quit"]
