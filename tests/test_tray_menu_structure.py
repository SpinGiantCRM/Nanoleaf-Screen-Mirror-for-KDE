from __future__ import annotations

from pathlib import Path


def test_tray_menu_groups_advanced_actions_under_submenu() -> None:
    text = Path("src/nanoleaf_sync/ui/tray_app.py").read_text(encoding="utf-8")
    assert 'advanced_menu = self.QMenu("Advanced / Troubleshooting", menu)' in text
    assert "menu.addMenu(advanced_menu)" in text


def test_tray_top_level_is_focused_for_daily_use() -> None:
    text = Path("src/nanoleaf_sync/ui/tray_app.py").read_text(encoding="utf-8")
    assert 'self.action_settings = self.QAction("Settings…", menu)' in text
    assert 'self.action_display_wizard = self.QAction("Calibration / Setup…", menu)' in text
    assert 'self.action_status = self.QAction("About / Status", menu)' in text
    assert 'self.action_advanced_settings = self.QAction("Advanced / Troubleshooting", menu)' in text
    assert "advanced_menu.addAction(self.action_advanced_settings)" in text
    assert "menu.addMenu(advanced_menu)" in text
    assert "menu.addAction(self.action_status)" in text
    assert text.index("menu.addMenu(advanced_menu)") < text.index("menu.addAction(self.action_status)")
    assert "Calibration tools moved to Settings" not in text
    assert 'self.on_settings(initial_section="Diagnostics", view_mode="advanced")' in text


def test_tray_tooltip_includes_backend_resolution_and_state_label() -> None:
    text = Path("src/nanoleaf_sync/ui/tray_app.py").read_text(encoding="utf-8")
    assert "Requested backend policy:" in text
    assert "Selected backend:" in text
    assert "Effective backend:" in text
    assert "About / Status (" in text


def test_tray_status_label_includes_app_version() -> None:
    text = Path("src/nanoleaf_sync/ui/tray_app.py").read_text(encoding="utf-8")
    assert "· v{self._app_version}" in text
