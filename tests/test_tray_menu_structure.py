from __future__ import annotations

from types import SimpleNamespace

import nanoleaf_sync
from nanoleaf_sync.ui.tray_app import (
    TRAY_MENU_ADVANCED_TITLE,
    TRAY_MENU_ICON_THEMES,
    NanoleafTrayApp,
    first_run_message,
)
from tests.qt_headless import find_submenu, load_headless_qt, make_tray_menu, submenu_action_texts


def _make_tray_status_stub(qt, *, app_version: str):
    tray = SimpleNamespace()
    tray.QIcon = qt["QIcon"]
    tray._app_version = app_version
    tray.config = SimpleNamespace(use_mock_capture=False, prefer_backend="auto")
    tray.service = SimpleNamespace(
        is_running=lambda: False,
        get_status=lambda: {"startup_state": "idle", "last_error": "", "mirroring_confidence": {}},
    )
    tray.tray_icon = qt["QSystemTrayIcon"]()
    tray.action_start = qt["QAction"]("Start")
    tray.action_stop = qt["QAction"]("Stop")
    tray.action_status = qt["QAction"]("About / Status")
    tray.action_enable_autostart = qt["QAction"]("Enable Autostart")
    tray.action_disable_autostart = qt["QAction"]("Disable Autostart")
    tray._idle_icon = qt["QIcon"]()
    tray._running_icon = qt["QIcon"]()
    tray._backend_icons = {}
    tray._tray_icon_for_status = lambda **kwargs: tray._idle_icon
    return tray


def test_tray_menu_groups_advanced_actions_under_submenu(monkeypatch) -> None:
    _qt, _app, _tray, menu = make_tray_menu(monkeypatch)
    advanced_menu = find_submenu(menu, TRAY_MENU_ADVANCED_TITLE)
    assert advanced_menu is not None
    assert advanced_menu.title() == TRAY_MENU_ADVANCED_TITLE


def test_tray_top_level_is_focused_for_daily_use(monkeypatch) -> None:
    _qt, _app, tray, menu = make_tray_menu(monkeypatch)
    assert hasattr(tray, "action_settings")
    assert hasattr(tray, "action_display_wizard")
    assert tray.action_display_wizard.text() == "Set up strip…"
    assert hasattr(tray, "action_status")
    assert not hasattr(tray, "action_advanced_settings")
    advanced_menu = find_submenu(menu, TRAY_MENU_ADVANCED_TITLE)
    assert advanced_menu is not None
    assert "Troubleshooting Guide" in submenu_action_texts(advanced_menu)

    ordered: list[str] = []
    for action in menu.actions():
        if action.isSeparator():
            continue
        sub = action.menu()
        ordered.append(sub.title() if sub is not None else action.text())
    assert ordered.index("About / Status") < ordered.index(TRAY_MENU_ADVANCED_TITLE)


def test_tray_tooltip_is_simplified_for_daily_use(monkeypatch) -> None:
    qt, app = load_headless_qt(monkeypatch)
    tray = _make_tray_status_stub(qt, app_version=nanoleaf_sync.__version__)
    NanoleafTrayApp._refresh_mode_labels(tray)  # type: ignore[arg-type]
    app.processEvents()
    tooltip = tray.tray_icon.toolTip()
    assert "Last issue:" in tooltip
    assert "Requested backend policy:" not in tooltip
    assert "Effective backend:" not in tooltip


def test_tray_copy_points_to_advanced_troubleshooting_guide() -> None:
    message = first_run_message("full-real")
    assert "Advanced → Troubleshooting Guide" in message
    assert "Help → Troubleshooting" not in message
    assert "Help / Troubleshooting" not in message
    assert "Opening Set up strip…" not in message


def test_tray_status_label_includes_app_version(monkeypatch) -> None:
    qt, app = load_headless_qt(monkeypatch)
    tray = _make_tray_status_stub(qt, app_version="9.9.9-test")
    NanoleafTrayApp._refresh_mode_labels(tray)  # type: ignore[arg-type]
    app.processEvents()
    assert "v9.9.9-test" in tray.action_status.text()


def test_tray_menu_has_system_theme_icons() -> None:
    assert TRAY_MENU_ICON_THEMES["action_start"] == "media-playback-start"
    assert TRAY_MENU_ICON_THEMES["action_stop"] == "media-playback-stop"
    assert TRAY_MENU_ICON_THEMES["action_settings"] == "preferences-system"
    assert TRAY_MENU_ICON_THEMES["action_display_wizard"] == "preferences-desktop-display"
    assert TRAY_MENU_ICON_THEMES["action_status"] == "help-about"
    assert TRAY_MENU_ICON_THEMES["action_quit"] == "application-exit"


def test_duplicate_troubleshooting_merged(monkeypatch) -> None:
    _qt, _app, tray, menu = make_tray_menu(monkeypatch)
    assert not hasattr(tray, "action_troubleshooting")
    assert not hasattr(NanoleafTrayApp, "on_troubleshooting")
    advanced_menu = find_submenu(menu, TRAY_MENU_ADVANCED_TITLE)
    assert advanced_menu is not None
    assert "Troubleshooting Guide" in submenu_action_texts(advanced_menu)
