import pytest

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.preset_ui import PERFORMANCE_PRIORITY_LABELS, PERFORMANCE_PROFILE_LABELS
from nanoleaf_sync.ui.settings_dialog import FPS_MAX, FPS_MIN, SettingsDialog
from tests.qt_headless import (
    button_texts,
    group_box_titles,
    label_texts,
    make_settings_dialog,
)


def test_settings_dialog_requires_qt_runtime(monkeypatch) -> None:
    def _raise():
        raise RuntimeError("PyQt6 is required for the tray UI.")

    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _raise)
    with pytest.raises(RuntimeError):
        SettingsDialog(None, AppConfig(), calibration_sender=None, runtime_status={})


def test_settings_dialog_source_uses_preset_ui_labels(monkeypatch) -> None:
    qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    assert hasattr(widget, "display_preset_combo")
    assert hasattr(widget, "performance_profile_combo")
    assert PERFORMANCE_PROFILE_LABELS
    assert hasattr(widget, "motion_preset_combo")
    assert hasattr(widget, "color_style_combo")
    assert "Advanced / Troubleshooting" in group_box_titles(widget, qt)
    labels = label_texts(widget, qt)
    assert any("Raw device→source mapping" in text for text in labels) or any(
        "Raw device→source mapping" in widget.diagnostics_mapping_label.text() for _ in [0]
    )
    assert any("HDR colour path" in text for text in labels) or "HDR colour path" in label_texts(
        widget, qt
    )
    assert "Runtime status (technical)" in group_box_titles(widget, qt)
    assert "Backend & Probing" in label_texts(widget, qt)
    assert "Diagnostics Actions" in label_texts(widget, qt)
    assert "Quality Diagnostics" in label_texts(widget, qt)
    assert "Recovery Tools" in label_texts(widget, qt)
    combined = " ".join(label_texts(widget, qt))
    assert "SDR white reference controls how bright SDR/desktop content appears" in combined
    assert "when HDR is enabled." in combined
    assert widget.windowTitle() == "nanoleaf-kde-sync Settings"


def test_settings_display_preset_change_updates_hdr_metadata_controls(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    widget.display_preset_combo.setCurrentIndex(max(0, widget.display_preset_combo.findText("HDR")))
    widget._on_display_preset_changed()
    assert widget._active_display_preset == "hdr"
    assert widget.hdr_transfer_combo.currentText() == "pq"
    assert widget.hdr_primaries_combo.currentText() == "bt2020"
    widget.display_preset_combo.setCurrentIndex(max(0, widget.display_preset_combo.findText("SDR")))
    widget._on_display_preset_changed()
    assert widget._active_display_preset == "sdr"
    assert widget.hdr_transfer_combo.currentText() == "srgb"
    assert widget.hdr_primaries_combo.currentText() == "bt709"


def test_advanced_troubleshooting_grid_rows_do_not_overlap(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    widget.focus_section("Advanced")
    assert widget.capture_monitor_edit is not None
    assert widget.retest_backends_button is not None
    assert widget.capture_backend_combo is not None


def test_color_preview_updates_are_debounced_for_calibration_sliders(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    assert widget._preview_refresh_timer.isSingleShot()
    assert widget.red_gain_slider.receivers(widget.red_gain_slider.valueChanged) >= 1
    widget._schedule_refresh_preview_label()
    assert widget._preview_refresh_timer.remainingTime() >= 0


def test_qt_loader_exports_settings_dialog_widgets() -> None:
    from nanoleaf_sync.ui.qt_lazy import load_qt

    qt = load_qt()
    assert "QLineEdit" in qt


def test_settings_dialog_opens_without_horizontal_scroll(monkeypatch) -> None:
    _qt, app, _dialog, widget = make_settings_dialog(monkeypatch)
    assert widget.size().width() >= 980
    assert widget.minimumSize().width() >= 980
    for index in range(widget._section_nav.count()):
        section = widget._section_nav.item(index).text()
        widget.focus_section(section)
        app.processEvents()
        page = widget._section_stack.currentWidget()
        if page.metaObject().className() == "QScrollArea":
            assert page.horizontalScrollBar().maximum() == 0


def test_settings_primary_sections_do_not_expose_raw_mapping_text(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    widget._refresh_preview_label()
    assert "Raw device→source mapping" not in widget.preview_label.text()
    assert "Raw device→source mapping" in widget.diagnostics_mapping_label.text()


def test_strip_count_mismatch_warning_text_present(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(
        monkeypatch,
        runtime_status={"device_zone_count": 60},
    )
    widget.device_zone_count_slider.setValue(40)
    widget.zone_count_slider.setValue(60)
    widget._state.corner_anchor_top_left = 40
    widget._refresh_preview_label()
    warning = widget.strip_count_warning_label.text()
    assert "Device-reported count differs from configured count." in warning
    assert "The configured manual value is used." in warning
    assert "Changing strip count invalidates calibration." in warning
    assert "Current anchors were assigned for a different strip length." in warning
    buttons = button_texts(widget, _qt)
    assert "Use reported count" in buttons
    assert "Keep manual count" in buttons


def test_sdr_white_reference_controls_present(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    buttons = button_texts(widget, _qt)
    assert "Detect KDE SDR white reference" in buttons
    assert "Use detected value" in buttons
    assert widget.sdr_boost_nits_slider.receivers(widget.sdr_boost_nits_slider.valueChanged) >= 1
    assert "Capture one diagnostic frame" in buttons
    assert "Export live sampling overlay" in buttons
    assert "Export synthetic sampling test overlay" in buttons


def test_fps_slider_label_value_and_tooltip_text(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    assert "Target capture/output FPS" in label_texts(widget, _qt)
    widget.fps_slider.setValue(45)
    widget._refresh_numeric_labels()
    assert widget.fps_value.text() == "45 FPS"
    tooltip = widget.fps_slider.toolTip()
    assert "This is the target update rate. Actual output FPS may be lower if capture," in tooltip
    assert "processing, or HID output cannot keep up." in tooltip
    assert widget.fps_slider.minimum() == FPS_MIN
    assert widget.fps_slider.maximum() == FPS_MAX
    assert FPS_MAX == 120
    assert "Capture backend" in label_texts(widget, _qt)
    assert widget.capture_backend_combo is not None


def test_slider_readouts_bind_live_value_updates(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    assert hasattr(widget, "_bind_live_numeric_updates")
    assert widget.brightness_slider.receivers(widget.brightness_slider.valueChanged) >= 1
    assert widget.smoothing_slider.receivers(widget.smoothing_slider.valueChanged) >= 1
    assert widget.fps_slider.receivers(widget.fps_slider.valueChanged) >= 1
    assert widget.hdr_max_nits_slider.receivers(widget.hdr_max_nits_slider.valueChanged) >= 1
    assert hasattr(widget, "black_luminance_knee_slider")
    assert widget.red_gain_slider.receivers(widget.red_gain_slider.valueChanged) >= 1


def test_settings_uses_stacked_widget_navigation(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    assert widget._section_stack is not None
    assert hasattr(widget, "_walk_strip_once")
    assert callable(widget._walk_strip_once)


def test_settings_layout_uses_consistent_spacing_helpers(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    assert hasattr(widget, "_configure_section_layout")
    assert hasattr(widget, "_help_text_label")
    assert hasattr(widget, "_configure_value_label")


def test_guided_led_calibration_controls_present(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    buttons = button_texts(widget, _qt)
    assert "Calibrate LED colour" in buttons
    assert "Black cutoff" in label_texts(widget, _qt)
    assert (
        "Neutral luminance: controls how bright grey/white screen areas"
        in widget.neutral_luminance_gain_slider.toolTip()
    )
    assert "appear on the LEDs." in widget.neutral_luminance_gain_slider.toolTip()
    assert (
        "Black cutoff: controls when near-black screen areas turn the LEDs off."
        in widget.black_luminance_cutoff_slider.toolTip()
    )
    from nanoleaf_sync.ui.led_color_calibration_dialog import LedColorCalibrationDialog

    assert LedColorCalibrationDialog is not None


def test_performance_priority_dropdown_present_and_persisted(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    assert "Performance priority" in label_texts(widget, _qt)
    assert hasattr(widget, "performance_priority_combo")
    assert any(label == "Very high experimental" for label, _ in PERFORMANCE_PRIORITY_LABELS)
    tooltip = widget.performance_priority_combo.toolTip()
    assert (
        "High priority may improve scheduling consistency. It may fail without permission."
        in tooltip
    )
    assert "Very high is experimental." in tooltip
    updated = widget.updated_config()
    assert updated.performance_priority in {value for _label, value in PERFORMANCE_PRIORITY_LABELS}


def test_save_applies_without_closing_dialog(monkeypatch) -> None:
    applied: list[AppConfig] = []

    def _on_apply(cfg: AppConfig) -> None:
        applied.append(cfg)

    qt, app, _dialog, widget = make_settings_dialog(monkeypatch)
    widget._on_apply = _on_apply
    widget._apply_settings()
    assert applied
    assert widget.settings_applied_in_session() is True


def test_settings_dialog_surfaces_latest_auto_and_manual_probe_results(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    assert hasattr(widget, "_update_latency_label_for_latest_probe_result")
    empty = widget._backend_probe_breakdown_text(selected_backend="none")
    assert "waiting for first result" in empty
    widget._probe_session_state["backend_probe_attempts"] = [
        {
            "backend": "kwin-dbus",
            "status": "tested",
            "mode": "fresh-probe",
            "sample_count": 2,
            "median_ms": 10.0,
            "p95_ms": 12.0,
            "jitter_ms": 1.0,
            "score": 0.8,
            "selected": True,
            "tentative": False,
            "reason": "ok",
        }
    ]
    manual = widget._backend_probe_breakdown_text(
        selected_backend="kwin-dbus",
        result_origin="manual",
    )
    assert "Last manual probe result." in manual
    assert "Candidate backends:" in manual
    assert hasattr(widget, "_update_backend_probe_button_state")
    assert hasattr(widget, "_backend_probe_blocked_by_runtime_state")


def test_sdr_white_preset_changed_uses_defensive_split_parsing(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    widget.sdr_white_reference_preset_combo.setCurrentIndex(3)
    widget._refresh_numeric_labels()
    assert widget.sdr_boost_nits_slider.value() == 203
    widget.sdr_white_reference_preset_combo.setCurrentIndex(
        widget.sdr_white_reference_preset_combo.findText("Custom")
    )
    widget._refresh_numeric_labels()
    assert widget.sdr_boost_nits_slider.value() == 203
