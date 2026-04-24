import pytest

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.display_configurator import DisplayConfiguratorDialog


def test_display_configurator_requires_qt_runtime() -> None:
    with pytest.raises(RuntimeError):
        DisplayConfiguratorDialog(None, AppConfig(), calibration_sender=None, runtime_status={})


def test_display_configurator_source_uses_new_preset_controls() -> None:
    text = open("src/nanoleaf_sync/ui/display_configurator.py", "r", encoding="utf-8").read()
    assert "display_preset_combo" in text
    assert "edge_locality_combo" in text
    assert "motion_preset_combo" in text
    assert "color_style_combo" in text
