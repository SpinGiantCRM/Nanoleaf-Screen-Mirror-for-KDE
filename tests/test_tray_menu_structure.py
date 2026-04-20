from __future__ import annotations

from pathlib import Path


def test_tray_menu_groups_advanced_actions_under_submenu() -> None:
    text = Path("src/nanoleaf_sync/ui/tray_app.py").read_text(encoding="utf-8")
    assert 'advanced_menu = self.QMenu("Troubleshooting / Advanced", menu)' in text
    assert "menu.addMenu(advanced_menu)" in text


def test_tray_top_level_is_focused_for_daily_use() -> None:
    text = Path("src/nanoleaf_sync/ui/tray_app.py").read_text(encoding="utf-8")
    assert 'self.action_display_wizard = self.QAction("Setup Wizard", menu)' in text
    assert 'self.action_status = self.QAction("Status / About", menu)' in text
