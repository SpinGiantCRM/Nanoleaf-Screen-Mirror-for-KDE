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
    def __init__(self, *, config):
        self.config = config

    def is_running(self):
        return False


class _FakeDialog:
    def __init__(self, parent, cfg):
        self._cfg = cfg

    def exec(self):
        return 1

    def wants_display_configurator(self):
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


def test_on_settings_replaces_service_with_updated_config(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.SettingsDialog", _FakeDialog)
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.NanoleafSyncService", _FakeService)

    fake_tray = SimpleNamespace(
        config=AppConfig(zones=[ZoneConfig(x=0.0, y=0.0, w=1.0, h=1.0)], device_zone_count=1),
        cfg_mgr=_FakeCfgMgr(),
        service=_FakeService(config=AppConfig(device_zone_count=1)),
        QDialog=SimpleNamespace(DialogCode=SimpleNamespace(Accepted=1)),
        _refresh_mode_labels=lambda: None,
        on_stop=lambda: None,
        on_start=lambda: None,
    )

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
        QDialog=SimpleNamespace(DialogCode=SimpleNamespace(Accepted=1)),
        _refresh_mode_labels=lambda: None,
        on_stop=lambda: None,
        on_start=lambda: None,
    )

    NanoleafTrayApp.on_settings(fake_tray)

    assert fake_tray.cfg_mgr.saved is None
    assert fake_tray.service.config.device_zone_count == 3
