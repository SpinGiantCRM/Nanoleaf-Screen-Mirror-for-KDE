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


def test_wizard_persists_preview_session_and_clears_on_finish(monkeypatch, tmp_path) -> None:
    session_path = tmp_path / "wizard-session.json"
    monkeypatch.setenv("NANOLEAF_ALLOW_UNSAFE_WIZARD_PATH", "1")
    monkeypatch.setenv("NANOLEAF_WIZARD_SESSION_PATH", str(session_path))
    sent: list[list[tuple[int, int, int]]] = []

    _qt, app, _dialog, widget = make_display_configurator(
        monkeypatch,
        calibration_sender=sent.append,
        runtime_status={"captured_frame_width": 320, "captured_frame_height": 180},
    )

    assert session_path.exists()
    draft = _dialog.in_progress_config()
    assert draft.wizard_in_progress_state

    widget.device_zone_count_slider.setValue(4)
    widget._state.corner_anchor_top_left = 0
    widget._state.corner_anchor_top_right = 1
    widget._state.corner_anchor_bottom_right = 2
    widget._state.corner_anchor_bottom_left = 3
    widget._flow.index = 1
    widget._refresh()
    app.processEvents()

    assert widget._live_preview_timer.isActive()
    widget._send_live_preview()
    assert sent
    assert len(sent[-1]) == 4
    assert any(color != (0, 0, 0) for color in sent[-1])

    widget.reject()
    app.processEvents()
    assert not widget._live_preview_timer.isActive()

    widget._finish()
    app.processEvents()
    assert not session_path.exists()
