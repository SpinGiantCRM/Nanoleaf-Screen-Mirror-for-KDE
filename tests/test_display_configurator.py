import pytest

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.display_configurator import DisplayConfiguratorDialog
from tests.repo_text import read_repo_text


def test_display_configurator_requires_qt_runtime(monkeypatch) -> None:
    def _raise():
        raise RuntimeError("PyQt6 is required for the tray UI.")

    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _raise)
    with pytest.raises(RuntimeError):
        DisplayConfiguratorDialog(None, AppConfig(), calibration_sender=None, runtime_status={})


def test_display_configurator_source_uses_new_preset_controls() -> None:
    text = read_repo_text("src/nanoleaf_sync/ui/display_configurator.py")
    assert "display_preset_combo" in text
    assert "edge_locality_combo" in text
    assert "motion_preset_combo" in text
    assert "color_style_combo" in text
    assert "preset_sdr_button" not in text
    assert "preset_hdr_button" not in text


def test_step1_primary_flow_hides_mapping_and_model_text() -> None:
    text = read_repo_text("src/nanoleaf_sync/ui/display_configurator.py")
    assert 'self.preview_visual.setText("")' in text
    assert 'self.calibration_diagnostics_group = QGroupBox("Diagnostics")' in text
    assert "Calibration model/internal resolver mode" in text
    assert "Device→source mapping list" in text


def test_step2_advanced_display_details_include_hdr_compositor_controls() -> None:
    text = read_repo_text("src/nanoleaf_sync/ui/display_configurator.py")
    assert "KDE SDR-on-HDR compensation / compositor HDR mode" in text
    assert 'QLabel("SDR white reference")' in text
    assert "SDR white reference preset" in text
    assert '"203 nits"' in text
