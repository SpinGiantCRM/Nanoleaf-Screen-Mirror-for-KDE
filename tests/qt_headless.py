from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


def load_headless_qt(monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("PyQt6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from nanoleaf_sync.ui.qt_lazy import load_qt

    qt = load_qt()
    app = qt["QApplication"].instance() or qt["QApplication"]([])
    return qt, app


def make_settings_dialog(monkeypatch: pytest.MonkeyPatch, **kwargs):
    from nanoleaf_sync.config.model import AppConfig
    from nanoleaf_sync.ui.settings_dialog import SettingsDialog

    qt, app = load_headless_qt(monkeypatch)
    dialog = SettingsDialog(
        None,
        AppConfig(),
        calibration_sender=kwargs.get("calibration_sender"),
        runtime_status=kwargs.get("runtime_status", {}),
    )
    widget = dialog._dialog
    widget.show()
    app.processEvents()
    return qt, app, dialog, widget


def make_display_configurator(monkeypatch: pytest.MonkeyPatch, **kwargs):
    from nanoleaf_sync.config.model import AppConfig
    from nanoleaf_sync.ui.display_configurator import DisplayConfiguratorDialog

    qt, app = load_headless_qt(monkeypatch)
    dialog = DisplayConfiguratorDialog(
        None,
        AppConfig(),
        calibration_sender=kwargs.get("calibration_sender"),
        runtime_status=kwargs.get("runtime_status", {}),
    )
    widget = dialog._dialog
    widget.show()
    app.processEvents()
    return qt, app, dialog, widget


def make_tray_menu(monkeypatch: pytest.MonkeyPatch):
    from nanoleaf_sync.ui.tray_app import NanoleafTrayApp

    qt, app = load_headless_qt(monkeypatch)
    tray = SimpleNamespace()
    tray.QMenu = qt["QMenu"]
    tray.QAction = qt["QAction"]
    tray.QIcon = qt["QIcon"]
    for name in (
        "on_start",
        "on_stop",
        "on_settings",
        "on_display_configurator",
        "on_guided_calibration",
        "on_open_troubleshooting_guide",
        "on_diagnostic_hub",
        "on_live_diagnostics",
        "on_status",
        "on_enable_autostart",
        "on_disable_autostart",
        "on_reset_probe_cache",
        "on_show_launch_diagnostics",
        "on_doctor",
        "on_smoke_test",
        "on_check_for_updates",
        "on_quit",
    ):
        setattr(tray, name, lambda *_args, **_kwargs: None)
    menu = NanoleafTrayApp._make_menu(tray)  # type: ignore[arg-type]
    return qt, app, tray, menu


def top_level_menu_actions(menu):
    return [action for action in menu.actions() if not action.isSeparator()]


def find_submenu(menu, title: str):
    for action in menu.actions():
        sub = action.menu()
        if sub is not None and sub.title() == title:
            return sub
    return None


def submenu_action_texts(submenu) -> list[str]:
    return [
        action.text()
        for action in submenu.actions()
        if not action.isSeparator() and action.menu() is None
    ]


def group_box_titles(widget, qt: dict[str, Any]) -> list[str]:
    QGroupBox = qt["QGroupBox"]
    return [box.title() for box in widget.findChildren(QGroupBox)]


def label_texts(widget, qt: dict[str, Any]) -> list[str]:
    QLabel = qt["QLabel"]
    return [label.text() for label in widget.findChildren(QLabel)]


def button_texts(widget, qt: dict[str, Any]) -> list[str]:
    QPushButton = qt["QPushButton"]
    return [button.text() for button in widget.findChildren(QPushButton)]
