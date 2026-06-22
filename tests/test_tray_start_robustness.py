from __future__ import annotations

from types import SimpleNamespace

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.output_session import OutputSessionController
from nanoleaf_sync.ui.tray_app import NanoleafTrayApp


class _FakeServiceOutputGuardMixin:
    mirroring_generation = 0

    def bind_mirroring_generation(self, generation: int) -> None:
        self.mirroring_generation = generation

    def set_output_session_guard(self, guard) -> None:
        self._output_session_guard = guard


class _FakeServiceRaises(_FakeServiceOutputGuardMixin):
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


class _FakeServiceFailedStart(_FakeServiceOutputGuardMixin):
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
    tray = SimpleNamespace(
        service=service,
        config=AppConfig(),
        cfg_mgr=SimpleNamespace(save=lambda _cfg: None),
        tray_icon=fake_icon,
        _idle_icon="idle",
        _running_icon="running",
        action_start=SimpleNamespace(
            setEnabled=lambda *_args, **_kwargs: None, setText=lambda *_args, **_kwargs: None
        ),
        action_status=SimpleNamespace(setText=lambda *_args, **_kwargs: None),
        _refresh_mode_labels=lambda: None,
        QSystemTrayIcon=SimpleNamespace(MessageIcon=SimpleNamespace(Warning=1)),
        _app_version="test",
        _messages=messages,
        _icon_updates=icon_updates,
        _preview_driver=None,
        _preview_paused_service=False,
        _preview_pause_notified=False,
        _output_session=OutputSessionController(),
    )
    tray._close_preview_driver = lambda: NanoleafTrayApp._close_preview_driver(tray)
    tray._sync_config_for_mirroring = lambda: NanoleafTrayApp._sync_config_for_mirroring(tray)
    tray._bind_output_session_guard = lambda svc: NanoleafTrayApp._bind_output_session_guard(
        tray, svc
    )
    return tray


class _FakeServiceWaitingStart(_FakeServiceOutputGuardMixin):
    last_error = None

    def __init__(self) -> None:
        self.start_calls = 0

    def start(self) -> bool:
        self.start_calls += 1
        return True

    def is_running(self) -> bool:
        return True

    def get_status(self) -> dict:
        return {"startup_state": "waiting_for_screen_selection"}


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


def test_on_start_is_idempotent_while_waiting_for_screen_selection() -> None:
    service = _FakeServiceWaitingStart()
    fake_tray = _tray_shell(service)

    NanoleafTrayApp.on_start(fake_tray)

    assert service.start_calls == 0


def test_run_opens_display_configurator_without_delayed_balloon_when_wizard_incomplete() -> None:
    opened = {"count": 0}
    app = SimpleNamespace(exec=lambda: 123)
    fake_tray_icon = SimpleNamespace(
        showMessage=lambda *_args, **_kwargs: opened.setdefault("balloon", True)
    )
    fake = SimpleNamespace(
        config=AppConfig(wizard_completed=False),
        tray_icon=fake_tray_icon,
        QSystemTrayIcon=SimpleNamespace(MessageIcon=SimpleNamespace(Information=1)),
        QTimer=SimpleNamespace(
            singleShot=lambda *_args, **_kwargs: opened.setdefault("delayed", True)
        ),
        on_display_configurator=lambda: opened.__setitem__("count", opened["count"] + 1),
        app=app,
    )

    rc = NanoleafTrayApp.run(fake)

    assert rc == 123
    assert opened["count"] == 1
    assert "delayed" not in opened
    assert "balloon" not in opened


def test_startup_launch_diagnostic_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("NANOLEAF_SHOW_STARTUP_DIAGNOSTIC", raising=False)
    fake = SimpleNamespace(_startup_warning=None, config=AppConfig(verbose=False))
    assert NanoleafTrayApp._should_show_startup_launch_diagnostic(fake) is False


def test_startup_launch_diagnostic_enabled_for_verbose_or_failure(monkeypatch) -> None:
    monkeypatch.delenv("NANOLEAF_SHOW_STARTUP_DIAGNOSTIC", raising=False)
    verbose_fake = SimpleNamespace(_startup_warning=None, config=AppConfig(verbose=True))
    failed_fake = SimpleNamespace(_startup_warning="load failed", config=AppConfig(verbose=False))
    assert NanoleafTrayApp._should_show_startup_launch_diagnostic(verbose_fake) is True
    assert NanoleafTrayApp._should_show_startup_launch_diagnostic(failed_fake) is True


def test_startup_launch_diagnostic_enabled_by_env(monkeypatch) -> None:
    monkeypatch.setenv("NANOLEAF_SHOW_STARTUP_DIAGNOSTIC", "debug")
    fake = SimpleNamespace(_startup_warning=None, config=AppConfig(verbose=False))
    assert NanoleafTrayApp._should_show_startup_launch_diagnostic(fake) is True
