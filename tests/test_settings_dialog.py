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
    assert 'QGroupBox("Diagnostics")' in text
    assert "Raw device→source mapping" in text
    assert "HDR colour path" in text
    assert "SDR white reference controls how bright SDR/desktop content appears when HDR is enabled." in text


def test_settings_primary_sections_do_not_expose_raw_mapping_text() -> None:
    text = open("src/nanoleaf_sync/ui/settings_dialog.py", "r", encoding="utf-8").read()
    assert "self.preview_label.setText(" in text
    assert "self._state.mapping_preview_text()" not in text.split("self.preview_label.setText(", 1)[1].split(")", 1)[0]


def test_strip_count_mismatch_warning_text_present() -> None:
    text = open("src/nanoleaf_sync/ui/settings_dialog.py", "r", encoding="utf-8").read()
    assert "Device-reported count differs from configured count. The configured manual value is used." in text
    assert "Changing strip count invalidates calibration." in text
    assert "Current anchors were assigned for a different strip length." in text
    assert "Use reported count" in text
    assert "Keep manual count" in text


def test_sdr_white_reference_controls_present() -> None:
    text = open("src/nanoleaf_sync/ui/settings_dialog.py", "r", encoding="utf-8").read()
    assert "Detect KDE SDR white reference" in text
    assert "Use detected value" in text
    assert "sdr_boost_nits_slider.valueChanged.connect(self._on_sdr_white_slider_changed)" in text
    assert "Capture one diagnostic frame" in text
    assert "Export live sampling overlay" in text
    assert "Export synthetic sampling test overlay" in text
