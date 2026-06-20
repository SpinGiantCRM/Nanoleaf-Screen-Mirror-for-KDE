from __future__ import annotations

from types import SimpleNamespace

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.ui.tray_app import NanoleafTrayApp


class _FakeCfgMgr:
    def __init__(self):
        self.saved = None

    def save(self, cfg):
        self.saved = cfg


class _FakeService:
    def __init__(self, *, config, running=False):
        self.config = config
        self._running = running

    def is_running(self):
        return self._running

    def get_status(self):
        return {}

    def start(self):
        self._running = True
        return True


class _FakeDialog:
    def __init__(self, parent, cfg, **_kwargs):
        self._cfg = cfg

    def exec(self):
        return 1

    def wants_display_configurator(self):
        return False

    def settings_applied_in_session(self):
        return False

    def updated_config(self):
        return AppConfig(
            zones=[ZoneConfig(x=0.0, y=0.0, w=0.5, h=1.0), ZoneConfig(x=0.5, y=0.0, w=0.5, h=1.0)],
            device_zone_count=0,
            output_channel_order="grb",
        )


class _FakeDialogCancel(_FakeDialog):
    def exec(self):
        return 0

    def settings_applied_in_session(self):
        return False


class _FakeDialogSaveThenClose(_FakeDialog):
    def __init__(self, parent, cfg, on_apply=None, **_kwargs):
        self._cfg = cfg
        self._on_apply = on_apply

    def exec(self):
        if callable(self._on_apply):
            self._on_apply(self.updated_config())
        return 0

    def settings_applied_in_session(self):
        return True

    def wants_display_configurator(self):
        return False

    def updated_config(self):
        return self._cfg


class _FakeDialogRerun(_FakeDialog):
    def wants_display_configurator(self):
        return True


def _wire_preview_helpers(fake_tray: SimpleNamespace) -> None:
    fake_tray._close_preview_driver = lambda: NanoleafTrayApp._close_preview_driver(fake_tray)
    fake_tray._sync_config_for_mirroring = lambda: NanoleafTrayApp._sync_config_for_mirroring(
        fake_tray
    )
    fake_tray._restart_mirroring_service = lambda *, was_running: (
        NanoleafTrayApp._restart_mirroring_service(fake_tray, was_running=was_running)
    )
    fake_tray._preview_driver = getattr(fake_tray, "_preview_driver", None)
    fake_tray._preview_paused_service = getattr(fake_tray, "_preview_paused_service", False)
    fake_tray._preview_pause_notified = getattr(fake_tray, "_preview_pause_notified", False)
    fake_tray._output_session = getattr(
        fake_tray, "_output_session", SimpleNamespace(release=lambda _owner: None)
    )
    if not hasattr(fake_tray, "tray_icon"):
        fake_tray.tray_icon = SimpleNamespace(showMessage=lambda *_a, **_k: None)
    if not hasattr(fake_tray, "QSystemTrayIcon"):
        fake_tray.QSystemTrayIcon = SimpleNamespace(
            MessageIcon=SimpleNamespace(Warning=1, Information=1)
        )


def test_on_settings_replaces_service_with_updated_config(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.SettingsDialog", _FakeDialog)
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.NanoleafSyncService", _FakeService)

    fake_tray = SimpleNamespace(
        config=AppConfig(zones=[ZoneConfig(x=0.0, y=0.0, w=1.0, h=1.0)], device_zone_count=1),
        cfg_mgr=_FakeCfgMgr(),
        service=_FakeService(config=AppConfig(device_zone_count=1), running=True),
        _calibration_dialog=None,
        QDialog=SimpleNamespace(DialogCode=SimpleNamespace(Accepted=1)),
        _refresh_mode_labels=lambda: None,
        _send_calibration_preview=lambda _colors: None,
        on_stop=lambda: None,
        on_start=lambda: None,
    )
    _wire_preview_helpers(fake_tray)

    NanoleafTrayApp.on_settings(fake_tray)

    assert fake_tray.cfg_mgr.saved is not None
    assert fake_tray.cfg_mgr.saved.device_zone_count == 0
    assert fake_tray.cfg_mgr.saved.output_channel_order == "grb"
    assert fake_tray.service.config.device_zone_count == 0
    assert fake_tray.service.config.output_channel_order == "grb"
    assert len(fake_tray.service.config.zones) == 2


def test_on_settings_cancel_discards_changes(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.SettingsDialog", _FakeDialogCancel)
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.NanoleafSyncService", _FakeService)

    original_cfg = AppConfig(device_zone_count=3, output_channel_order="rgb")
    fake_tray = SimpleNamespace(
        config=original_cfg,
        cfg_mgr=_FakeCfgMgr(),
        service=_FakeService(config=original_cfg),
        _calibration_dialog=None,
        QDialog=SimpleNamespace(DialogCode=SimpleNamespace(Accepted=1)),
        _refresh_mode_labels=lambda: None,
        _send_calibration_preview=lambda _colors: None,
        on_stop=lambda: None,
        on_start=lambda: None,
    )
    _wire_preview_helpers(fake_tray)

    NanoleafTrayApp.on_settings(fake_tray)

    assert fake_tray.cfg_mgr.saved is None
    assert fake_tray.service.config.device_zone_count == 3


def test_on_settings_save_then_close_skips_second_start(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.SettingsDialog", _FakeDialogSaveThenClose)
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.NanoleafSyncService", _FakeService)

    starts = {"count": 0}
    original_cfg = AppConfig(device_zone_count=3, output_channel_order="rgb")
    fake_tray = SimpleNamespace(
        config=original_cfg,
        cfg_mgr=_FakeCfgMgr(),
        service=_FakeService(config=original_cfg, running=True),
        _calibration_dialog=None,
        QDialog=SimpleNamespace(DialogCode=SimpleNamespace(Accepted=1)),
        _refresh_mode_labels=lambda: None,
        _send_calibration_preview=lambda _colors: None,
        on_stop=lambda: None,
        on_start=lambda: starts.__setitem__("count", starts["count"] + 1),
    )
    _wire_preview_helpers(fake_tray)

    NanoleafTrayApp.on_settings(fake_tray)

    assert starts["count"] == 1
    assert fake_tray.cfg_mgr.saved is not None


def test_on_settings_cancel_resumes_mirroring(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.SettingsDialog", _FakeDialogCancel)
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.NanoleafSyncService", _FakeService)

    starts = {"count": 0}
    original_cfg = AppConfig(device_zone_count=3, output_channel_order="rgb")
    fake_tray = SimpleNamespace(
        config=original_cfg,
        cfg_mgr=_FakeCfgMgr(),
        service=_FakeService(config=original_cfg, running=False),
        _calibration_dialog=None,
        QDialog=SimpleNamespace(DialogCode=SimpleNamespace(Accepted=1)),
        QSystemTrayIcon=SimpleNamespace(MessageIcon=SimpleNamespace(Warning=1)),
        tray_icon=SimpleNamespace(showMessage=lambda *_a, **_k: None),
        _refresh_mode_labels=lambda: None,
        _send_calibration_preview=lambda _colors: None,
        on_stop=lambda: None,
        on_start=lambda: starts.__setitem__("count", starts["count"] + 1),
        _close_preview_driver=lambda: True,
        _restart_mirroring_service=lambda *, was_running: (
            starts.__setitem__("count", starts["count"] + 1) if was_running else None
        ),
        _preview_paused_service=True,
    )

    NanoleafTrayApp.on_settings(fake_tray)

    assert starts["count"] == 1


def test_on_settings_open_failure_shows_message(monkeypatch) -> None:
    def _raise(*_args, **_kwargs):
        raise RuntimeError("dialog init failed")

    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.SettingsDialog", _raise)

    messages: list[str] = []
    fake_tray = SimpleNamespace(
        config=AppConfig(device_zone_count=1),
        cfg_mgr=_FakeCfgMgr(),
        service=_FakeService(config=AppConfig(device_zone_count=1), running=True),
        QDialog=SimpleNamespace(DialogCode=SimpleNamespace(Accepted=1)),
        QSystemTrayIcon=SimpleNamespace(MessageIcon=SimpleNamespace(Warning=1)),
        tray_icon=SimpleNamespace(
            showMessage=lambda _title, message, *_a, **_k: messages.append(str(message))
        ),
        _refresh_mode_labels=lambda: None,
        _send_calibration_preview=lambda _colors: None,
        on_stop=lambda: None,
        on_start=lambda: None,
        _close_preview_driver=lambda: False,
        _preview_paused_service=False,
    )

    NanoleafTrayApp.on_settings(fake_tray)

    assert messages
    assert "dialog init failed" in messages[0]


def test_on_settings_rerun_display_setup_persists_pending_settings(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.SettingsDialog", _FakeDialogRerun)

    fake_tray = SimpleNamespace(
        config=AppConfig(zones=[ZoneConfig(x=0.0, y=0.0, w=1.0, h=1.0)], device_zone_count=1),
        cfg_mgr=_FakeCfgMgr(),
        service=_FakeService(config=AppConfig(device_zone_count=1)),
        QDialog=SimpleNamespace(DialogCode=SimpleNamespace(Accepted=1)),
        _refresh_mode_labels=lambda: None,
        _send_calibration_preview=lambda _colors: None,
        on_stop=lambda: None,
        on_start=lambda: None,
        _close_preview_driver=lambda: False,
        _restart_mirroring_service=lambda *, was_running: None,
        _calibration_dialog=None,
        wizard_opened=False,
    )

    def _open(*, was_running_intent=None):
        assert was_running_intent is False
        fake_tray.wizard_opened = True

    fake_tray.on_display_configurator = _open

    NanoleafTrayApp.on_settings(fake_tray)

    assert fake_tray.wizard_opened is True
    assert fake_tray.cfg_mgr.saved is not None
    assert fake_tray.cfg_mgr.saved.device_zone_count == 0


def test_on_settings_rerun_display_setup_restarts_when_running_before_settings(monkeypatch) -> None:
    class _FakeDisplayConfiguratorDialog:
        def __init__(self, parent, cfg, **_kwargs):
            self._cfg = cfg

        def exec(self):
            return 1

        def updated_config(self):
            return AppConfig(
                zones=[ZoneConfig(x=0.0, y=0.0, w=1.0, h=1.0)],
                device_zone_count=0,
                wizard_completed=True,
            )

    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.SettingsDialog", _FakeDialogRerun)
    monkeypatch.setattr(
        "nanoleaf_sync.ui.tray_app.DisplayConfiguratorDialog", _FakeDisplayConfiguratorDialog
    )
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.NanoleafSyncService", _FakeService)

    class _TrayIcon:
        def showMessage(self, *_args, **_kwargs):
            return None

    starts = {"count": 0}
    fake_tray = SimpleNamespace(
        config=AppConfig(zones=[ZoneConfig(x=0.0, y=0.0, w=1.0, h=1.0)], device_zone_count=1),
        cfg_mgr=_FakeCfgMgr(),
        service=_FakeService(config=AppConfig(device_zone_count=1)),
        QDialog=SimpleNamespace(DialogCode=SimpleNamespace(Accepted=1)),
        QSystemTrayIcon=SimpleNamespace(MessageIcon=SimpleNamespace(Information=1)),
        _refresh_mode_labels=lambda: None,
        _send_calibration_preview=lambda _colors: None,
        _close_preview_driver=lambda: setattr(fake_tray, "_preview_paused_service", False) or True,
        _preview_paused_service=True,
        tray_icon=_TrayIcon(),
        _calibration_dialog=None,
    )

    def _on_start():
        starts["count"] += 1

    fake_tray.on_start = _on_start
    fake_tray.on_stop = lambda: None
    fake_tray._restart_mirroring_service = lambda *, was_running: (
        _on_start() if was_running else None
    )
    fake_tray.on_display_configurator = lambda *, was_running_intent=None: (
        NanoleafTrayApp.on_display_configurator(fake_tray, was_running_intent=was_running_intent)
    )

    NanoleafTrayApp.on_settings(fake_tray)

    assert starts["count"] == 1
