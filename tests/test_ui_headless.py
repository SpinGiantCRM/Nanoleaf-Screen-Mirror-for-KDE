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
        _close_preview_driver=None,
    )

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
