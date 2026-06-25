import pytest

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.display_configurator import DisplayConfiguratorDialog
from tests.qt_headless import group_box_titles, label_texts, make_display_configurator


def test_display_configurator_requires_qt_runtime(monkeypatch) -> None:
    def _raise():
        raise RuntimeError("PyQt6 is required for the tray UI.")

    monkeypatch.setattr("nanoleaf_sync.ui.display_configurator.load_qt", _raise)
    with pytest.raises(RuntimeError):
        DisplayConfiguratorDialog(None, AppConfig(), calibration_sender=None, runtime_status={})


def test_display_configurator_source_uses_new_preset_controls(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_display_configurator(monkeypatch)
    assert hasattr(widget, "display_preset_combo")
    assert hasattr(widget, "edge_locality_combo")
    assert hasattr(widget, "motion_preset_combo")
    assert hasattr(widget, "color_style_combo")
    assert not hasattr(widget, "preset_sdr_button")
    assert not hasattr(widget, "preset_hdr_button")


def test_step1_primary_flow_hides_mapping_and_model_text(monkeypatch) -> None:
    qt, _app, _dialog, widget = make_display_configurator(monkeypatch)
    widget._flow.index = 0
    widget._refresh()
    assert widget.preview_visual.text() == ""
    assert "Technical details" in group_box_titles(widget, qt)
    labels = label_texts(widget, qt)
    assert any(
        "How many addressable lighting zones does your strip have?" in text for text in labels
    )
    assert any("Calibration model/internal resolver mode" in text for text in labels)
    assert any("Device→source mapping list" in text for text in labels)


def test_wizard_finish_enables_real_screen_capture(monkeypatch) -> None:
    _qt, _app, dialog, widget = make_display_configurator(monkeypatch)
    widget._flow.index = widget._flow.total_steps - 1
    widget._refresh()
    finished = dialog.updated_config()
    assert finished.use_mock_capture is False


def test_step2_advanced_display_details_include_hdr_compositor_controls(monkeypatch) -> None:
    qt, _app, _dialog, widget = make_display_configurator(monkeypatch)
    widget._flow.index = 1
    widget._refresh()
    assert (
        widget.compositor_hdr_mode_checkbox.text()
        == "KDE SDR-on-HDR compensation / compositor HDR mode"
    )
    labels = label_texts(widget, qt)
    assert widget.compositor_hdr_mode_checkbox.isCheckable() or hasattr(
        widget.compositor_hdr_mode_checkbox, "isChecked"
    )
    assert any("SDR white reference" in text for text in labels)
    preset_items = [
        widget.sdr_white_reference_preset_combo.itemText(i)
        for i in range(widget.sdr_white_reference_preset_combo.count())
    ]
    assert "203 nits" in preset_items
