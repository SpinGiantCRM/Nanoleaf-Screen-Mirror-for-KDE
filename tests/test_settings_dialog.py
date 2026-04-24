import pytest

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.settings_dialog import SettingsDialog


def test_settings_dialog_requires_qt_runtime() -> None:
    with pytest.raises(RuntimeError):
        SettingsDialog(None, AppConfig(), calibration_sender=None, runtime_status={})


def test_settings_dialog_source_uses_preset_ui_labels() -> None:
    text = open("src/nanoleaf_sync/ui/settings_dialog.py", "r", encoding="utf-8").read()
    assert "display_preset_combo" in text
    assert "layout_preset_combo" in text
    assert "motion_preset_combo" in text
    assert "color_style_combo" in text
