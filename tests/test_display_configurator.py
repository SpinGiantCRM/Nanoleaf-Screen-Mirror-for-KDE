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
    assert "preset_sdr_button" not in text
    assert "preset_hdr_button" not in text


def test_step1_primary_flow_hides_mapping_and_model_text() -> None:
    text = open("src/nanoleaf_sync/ui/display_configurator.py", "r", encoding="utf-8").read()
    assert "self.preview_visual.setText(\"\")" in text
    assert "self.calibration_diagnostics_group = QGroupBox(\"Diagnostics\")" in text
    assert "Calibration model/internal resolver mode" in text
    assert "Device→source mapping list" in text


def test_step2_advanced_display_details_include_hdr_compositor_controls() -> None:
    text = open("src/nanoleaf_sync/ui/display_configurator.py", "r", encoding="utf-8").read()
    assert "KDE SDR-on-HDR compensation / compositor HDR mode" in text
    assert 'QLabel("SDR white reference")' in text
    assert "SDR white reference preset" in text
    assert "\"203 nits\"" in text
