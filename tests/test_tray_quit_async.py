from __future__ import annotations

import time
from types import SimpleNamespace

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.output_session import OutputSessionController
from nanoleaf_sync.ui.tray_app import NanoleafTrayApp


class _FakeService:
    def __init__(self) -> None:
        self.stop_calls = 0
        self._running = True

    def stop(self) -> None:
        self.stop_calls += 1

    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> dict:
        return {"startup_state": "running" if self._running else "idle"}


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
        _close_preview_driver=lambda: False,
    )
    fake_tray._request_stop = lambda: NanoleafTrayApp._request_stop(fake_tray)
    fake_tray._safe_refresh_mode_labels = lambda: NanoleafTrayApp._safe_refresh_mode_labels(
        fake_tray
    )
    fake_tray._set_idle_ui_state = lambda: NanoleafTrayApp._set_idle_ui_state(fake_tray)
    fake_tray._poll_shutdown_completion = lambda: NanoleafTrayApp._poll_shutdown_completion(
        fake_tray
    )
    fake_tray._finalize_quit = lambda: NanoleafTrayApp._finalize_quit(fake_tray)
    turn_off_calls: list[str] = []
    service.turn_off_lights = lambda: turn_off_calls.append("off") or True

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
    assert turn_off_calls == ["off"]


class _FakeServiceStopTimeout(_FakeService):
    def stop(self, timeout=1.5):  # noqa: ARG002 - signature matches real service
        self.stop_calls += 1
        return False


def test_on_stop_reports_timeout_without_pretending_idle() -> None:
    service = _FakeServiceStopTimeout()
    messages: list[str] = []
    icons: list[str] = []
    timer = _FakeTimer()
    fake_tray = SimpleNamespace(
        service=service,
        QTimer=timer,
        tray_icon=SimpleNamespace(
            setIcon=lambda icon: icons.append(icon),
            showMessage=lambda _title, text, _icon, _timeout: messages.append(text),
        ),
        _idle_icon="idle",
        _running_icon="running",
        _refresh_mode_labels=lambda: None,
        _shutdown_in_progress=False,
        _shutdown_timeout_s=0.1,
        _stop_poll_deadline=0.0,
        _stop_poll_count=0,
        _schedule_stop_warning=lambda _svc: None,
        QSystemTrayIcon=SimpleNamespace(MessageIcon=SimpleNamespace(Warning=2)),
    )
    fake_tray._service_running = lambda svc=None: NanoleafTrayApp._service_running(fake_tray, svc)
    fake_tray._request_stop = lambda **kwargs: NanoleafTrayApp._request_stop(fake_tray, **kwargs)
    fake_tray._safe_refresh_mode_labels = lambda: NanoleafTrayApp._safe_refresh_mode_labels(
        fake_tray
    )
    fake_tray._set_idle_ui_state = lambda: NanoleafTrayApp._set_idle_ui_state(fake_tray)
    fake_tray._poll_stop_completion = lambda: NanoleafTrayApp._poll_stop_completion(fake_tray)

    NanoleafTrayApp.on_stop(fake_tray)

    assert service.stop_calls == 1
    # on_stop sets _stop_poll_deadline to a future time and starts polling.
    # The first poll tick sees the future deadline and schedules another tick.
    assert len(timer.pending) == 1
    _delay, callback = timer.pending.pop(0)
    # Advance the poll deadline to the past so the next callback hits the
    # deadline path.
    fake_tray._stop_poll_deadline = time.monotonic() - 1.0
    callback()

    # After the poll deadline, the timeout message should appear.
    assert any("still stopping" in msg for msg in messages)


class _FakeServiceStateError(_FakeService):
    def is_running(self) -> bool:
        raise RuntimeError("runtime state unavailable")


def test_on_stop_handles_service_state_query_errors_without_exiting() -> None:
    service = _FakeServiceStateError()
    messages: list[str] = []
    icons: list[str] = []
    quit_calls: list[str] = []
    timer = _FakeTimer()
    fake_tray = SimpleNamespace(
        service=service,
        app=SimpleNamespace(quit=lambda: quit_calls.append("quit")),
        QTimer=timer,
        tray_icon=SimpleNamespace(
            setIcon=lambda icon: icons.append(icon),
            showMessage=lambda _title, text, _icon, _timeout: messages.append(text),
        ),
        _idle_icon="idle",
        _running_icon="running",
        _refresh_mode_labels=lambda: None,
        _shutdown_in_progress=False,
        _shutdown_timeout_s=0.1,
        _stop_poll_deadline=0.0,
        _stop_poll_count=0,
        _schedule_stop_warning=lambda _svc: None,
        QSystemTrayIcon=SimpleNamespace(MessageIcon=SimpleNamespace(Warning=2)),
    )
    fake_tray._service_running = lambda svc=None: NanoleafTrayApp._service_running(fake_tray, svc)
    fake_tray._request_stop = lambda **kwargs: NanoleafTrayApp._request_stop(fake_tray, **kwargs)
    fake_tray._safe_refresh_mode_labels = lambda: NanoleafTrayApp._safe_refresh_mode_labels(
        fake_tray
    )
    fake_tray._set_idle_ui_state = lambda: NanoleafTrayApp._set_idle_ui_state(fake_tray)
    fake_tray._poll_stop_completion = lambda: NanoleafTrayApp._poll_stop_completion(fake_tray)

    NanoleafTrayApp.on_stop(fake_tray)

    assert service.stop_calls == 1
    assert icons[-1] == "idle"
    assert messages == []
    assert quit_calls == []


class _FakeServiceStartFailure:
    mirroring_generation = 0

    def __init__(self) -> None:
        self.stop_calls = 0
        self.start_calls = 0
        self._running = False
        self.last_error = "simulated start failure"

    def bind_mirroring_generation(self, generation: int) -> None:
        self.mirroring_generation = generation

    def set_output_session_guard(self, guard) -> None:
        self._output_session_guard = guard

    def start(self) -> bool:
        self.start_calls += 1
        return False

    def stop(self, timeout=1.5):  # noqa: ARG002 - compatibility with real service API
        self.stop_calls += 1
        return True

    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> dict:
        return {
            "startup_state": "error",
            "last_error_guidance": "Use diagnostics.",
        }


def test_on_start_failure_stays_alive_and_stop_after_failure_is_safe() -> None:
    service = _FakeServiceStartFailure()
    messages: list[str] = []
    icons: list[str] = []
    quit_calls: list[str] = []
    fake_tray = SimpleNamespace(
        service=service,
        config=AppConfig(),
        cfg_mgr=SimpleNamespace(save=lambda _cfg: None),
        tray_icon=SimpleNamespace(
            setIcon=lambda icon: icons.append(icon),
            showMessage=lambda _title, text, _icon, _timeout: messages.append(text),
        ),
        app=SimpleNamespace(quit=lambda: quit_calls.append("quit")),
        _idle_icon="idle",
        _running_icon="running",
        _close_preview_driver=lambda: False,
        _output_session=OutputSessionController(),
        _refresh_mode_labels=lambda: None,
        _shutdown_in_progress=False,
        _shutdown_timeout_s=0.1,
        _schedule_stop_warning=lambda _svc: None,
        QSystemTrayIcon=SimpleNamespace(
            MessageIcon=SimpleNamespace(Warning=2, Information=1),
        ),
    )
    fake_tray._safe_service_status = lambda: NanoleafTrayApp._safe_service_status(fake_tray)
    fake_tray._safe_refresh_mode_labels = lambda: NanoleafTrayApp._safe_refresh_mode_labels(
        fake_tray
    )
    fake_tray._service_running = lambda svc=None: NanoleafTrayApp._service_running(fake_tray, svc)
    fake_tray._request_stop = lambda **kwargs: NanoleafTrayApp._request_stop(fake_tray, **kwargs)
    fake_tray._set_idle_ui_state = lambda: NanoleafTrayApp._set_idle_ui_state(fake_tray)
    fake_tray._sync_config_for_mirroring = lambda: NanoleafTrayApp._sync_config_for_mirroring(
        fake_tray
    )
    fake_tray._bind_output_session_guard = lambda svc: NanoleafTrayApp._bind_output_session_guard(
        fake_tray, svc
    )

    NanoleafTrayApp.on_start(fake_tray)
    NanoleafTrayApp.on_stop(fake_tray)

    assert service.start_calls == 1
    assert service.stop_calls == 1
    assert icons[0] == "idle"
    assert any("Start failed" in msg for msg in messages)
    assert quit_calls == []


class _FakeServiceStatusCrash(_FakeServiceStartFailure):
    def get_status(self) -> dict:
        raise RuntimeError("status unavailable")


def test_on_start_contains_status_exceptions_at_callback_boundary() -> None:
    service = _FakeServiceStatusCrash()
    messages: list[str] = []
    fake_tray = SimpleNamespace(
        service=service,
        config=AppConfig(),
        cfg_mgr=SimpleNamespace(save=lambda _cfg: None),
        tray_icon=SimpleNamespace(
            setIcon=lambda _icon: None,
            showMessage=lambda _title, text, _icon, _timeout: messages.append(text),
        ),
        _idle_icon="idle",
        _running_icon="running",
        _close_preview_driver=lambda: False,
        _output_session=OutputSessionController(),
        _refresh_mode_labels=lambda: (_ for _ in ()).throw(RuntimeError("ui unavailable")),
        QSystemTrayIcon=SimpleNamespace(
            MessageIcon=SimpleNamespace(Warning=2, Information=1),
        ),
    )
    fake_tray._safe_service_status = lambda: NanoleafTrayApp._safe_service_status(fake_tray)
    fake_tray._safe_refresh_mode_labels = lambda: NanoleafTrayApp._safe_refresh_mode_labels(
        fake_tray
    )
    fake_tray._sync_config_for_mirroring = lambda: NanoleafTrayApp._sync_config_for_mirroring(
        fake_tray
    )
    fake_tray._bind_output_session_guard = lambda svc: NanoleafTrayApp._bind_output_session_guard(
        fake_tray, svc
    )

    NanoleafTrayApp.on_start(fake_tray)

    assert service.start_calls == 1
    assert any("Start failed" in msg for msg in messages)
