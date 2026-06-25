from __future__ import annotations

from types import SimpleNamespace

import pytest

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.ui.tray_app import NanoleafTrayApp
from nanoleaf_sync.ui.zone_calibration import strip_corner_diagram


class _FakeCfgMgr:
    def __init__(self) -> None:
        self.saved = None

    def save(self, cfg: AppConfig) -> None:
        self.saved = cfg


class _FakeService:
    def __init__(self, *, config: AppConfig, running: bool = False) -> None:
        self.config = config
        self._running = running

    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> dict:
        return {}

    def start(self) -> bool:
        self._running = True
        return True

    def stop(self) -> bool:
        self._running = False
        return True


def _wire_preview_helpers(fake_tray: SimpleNamespace) -> None:
    fake_tray._close_preview_driver = lambda: NanoleafTrayApp._close_preview_driver(fake_tray)
    fake_tray._sync_config_for_mirroring = lambda: NanoleafTrayApp._sync_config_for_mirroring(
        fake_tray
    )
    fake_tray._restart_mirroring_service = lambda *, was_running: (
        NanoleafTrayApp._restart_mirroring_service(fake_tray, was_running=was_running)
    )
    fake_tray._request_stop = lambda *args, **kwargs: fake_tray.on_stop()
    fake_tray._shutdown_timeout_s = 5.0
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


class _FakeDialogSaveThenClose:
    def __init__(self, parent, cfg, **_kwargs) -> None:
        self._cfg = cfg
        self._applied = False

    def exec(self) -> int:
        return 0

    def settings_applied_in_session(self) -> bool:
        return self._applied

    def wants_display_configurator(self) -> bool:
        return False

    def updated_config(self) -> AppConfig:
        return self._cfg


def test_on_settings_save_then_close_starts_once(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Dialog(_FakeDialogSaveThenClose):
        def __init__(self, parent, cfg, on_apply=None, **_kwargs) -> None:
            super().__init__(parent, cfg, **_kwargs)
            self._on_apply = on_apply

        def exec(self) -> int:
            if callable(self._on_apply):
                self._on_apply(self.updated_config())
                self._applied = True
            return 0

    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.SettingsDialog", _Dialog)
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.NanoleafSyncService", _FakeService)

    starts = {"count": 0}
    fake_tray = SimpleNamespace(
        config=AppConfig(zones=[ZoneConfig(x=0.0, y=0.0, w=1.0, h=1.0)], device_zone_count=1),
        cfg_mgr=_FakeCfgMgr(),
        service=_FakeService(config=AppConfig(device_zone_count=1), running=True),
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


def test_strip_corner_diagram_marks_active_corner() -> None:
    diagram = strip_corner_diagram(active_corner="top_left")
    assert "[TL*]" in diagram
    assert " TR " in diagram


@pytest.mark.parametrize(
    ("name", "expected_suffix"),
    [
        ("TROUBLESHOOTING.md", "TROUBLESHOOTING.md"),
    ],
)
def test_resolve_user_doc_headless(name: str, expected_suffix: str) -> None:
    from nanoleaf_sync.doc_paths import resolve_user_doc

    path = resolve_user_doc(name)
    assert path is not None
    assert path.name == expected_suffix


def test_settings_save_while_mirroring_restarts_once(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Dialog(_FakeDialogSaveThenClose):
        def __init__(self, parent, cfg, on_apply=None, **_kwargs) -> None:
            super().__init__(parent, cfg, **_kwargs)
            self._on_apply = on_apply

        def exec(self) -> int:
            if callable(self._on_apply):
                self._on_apply(AppConfig(device_zone_count=4, fps=90))
                self._applied = True
            return 0

    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.SettingsDialog", _Dialog)
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.NanoleafSyncService", _FakeService)

    restarts = {"count": 0}
    fake_tray = SimpleNamespace(
        config=AppConfig(device_zone_count=4, fps=30),
        cfg_mgr=_FakeCfgMgr(),
        service=_FakeService(config=AppConfig(device_zone_count=4, fps=30), running=True),
        _calibration_dialog=None,
        QDialog=SimpleNamespace(DialogCode=SimpleNamespace(Accepted=1)),
        _refresh_mode_labels=lambda: None,
        _send_calibration_preview=lambda _colors: None,
        on_stop=lambda: None,
        on_start=lambda: restarts.__setitem__("count", restarts["count"] + 1),
    )
    _wire_preview_helpers(fake_tray)

    NanoleafTrayApp.on_settings(fake_tray)

    assert fake_tray.cfg_mgr.saved is not None
    assert fake_tray.cfg_mgr.saved.fps == 90
    assert restarts["count"] == 1


def test_calibration_wizard_state_surfaces_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.qt_headless import make_settings_dialog

    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    widget._state.corner_anchor_top_left = -1
    widget._refresh_preview_label()
    assert "Missing corners" in widget.simple_calibration_widget.validation_label.text()


def test_display_preset_switch_updates_hdr_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.qt_headless import make_settings_dialog

    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    widget.display_preset_combo.setCurrentIndex(max(0, widget.display_preset_combo.findText("HDR")))
    widget._on_display_preset_changed()
    assert widget._active_display_preset == "hdr"
    assert widget.hdr_transfer_combo.currentText() == "pq"


def test_preview_refresh_restart_is_debounced(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.qt_headless import make_settings_dialog

    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    assert widget._preview_refresh_timer.isSingleShot()
    widget._schedule_refresh_preview_label()
    assert widget._preview_refresh_timer.remainingTime() >= 0
    widget.red_gain_slider.setValue(widget.red_gain_slider.value() + 1)
    widget._schedule_refresh_preview_label()
    assert widget._preview_refresh_timer.remainingTime() >= 0


def test_diagnostics_rendering_includes_mapping_and_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.qt_headless import make_settings_dialog

    _qt, _app, _dialog, widget = make_settings_dialog(
        monkeypatch,
        runtime_status={"startup_state": "running", "effective_fps": 30.0},
    )
    widget._refresh_preview_label()
    mapping = widget.diagnostics_mapping_label.text()
    assert "Raw device→source mapping" in mapping
    assert "Requested backend policy" in widget.backend_info_label.text()


def test_invalid_config_recovery_normalizes_device_zone_count(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from nanoleaf_sync.config.store import ConfigManager
    from tests.qt_headless import make_settings_dialog

    path = tmp_path / "config.toml"
    path.write_text("device_zone_count = -5\n", encoding="utf-8")
    recovered = ConfigManager(path).load()
    assert recovered.device_zone_count >= 0
    assert path.with_suffix(path.suffix + ".invalid").exists()

    _qt, _app, _dialog, widget = make_settings_dialog(
        monkeypatch,
        cfg=recovered,
        runtime_status={"device_zone_count": 60},
    )
    widget.device_zone_count_slider.setValue(max(1, recovered.device_zone_count or 40))
    widget._refresh_preview_label()
    assert widget.strip_count_warning_label.text() or widget.backend_info_label.text()
