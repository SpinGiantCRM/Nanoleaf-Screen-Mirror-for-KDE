import pytest

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.settings_dialog import SettingsDialog
from tests.repo_text import normalized_repo_text, read_repo_text, source_contains_all


def test_settings_dialog_requires_qt_runtime(monkeypatch) -> None:
    def _raise():
        raise RuntimeError("PyQt6 is required for the tray UI.")

    monkeypatch.setattr("nanoleaf_sync.ui.settings_dialog.load_qt", _raise)
    with pytest.raises(RuntimeError):
        SettingsDialog(None, AppConfig(), calibration_sender=None, runtime_status={})


def test_settings_dialog_source_uses_preset_ui_labels() -> None:
    text = read_repo_text("src/nanoleaf_sync/ui/settings_dialog.py")
    assert "display_preset_combo" in text
    assert "layout_preset" in text
    assert "motion_preset_combo" in text
    assert "color_style_combo" in text
    assert (
        'QGroupBox("Advanced / Troubleshooting")' in text
        or 'QGroupBox("Advanced Settings")' in text
    )
    assert "Raw device→source mapping" in text
    assert "HDR colour path" in text
    assert "Runtime status (technical)" in text
    assert "Backend & Probing" in text
    assert "Diagnostics Actions" in text
    assert "Quality Diagnostics" in text
    assert "Recovery Tools" in text
    assert source_contains_all(
        "src/nanoleaf_sync/ui/settings_dialog.py",
        "SDR white reference controls how bright SDR/desktop content appears",
        "when HDR is enabled.",
    )
    assert "window_title = " in text
    assert '"nanoleaf-kde-sync Settings"' in text


def test_settings_primary_sections_do_not_expose_raw_mapping_text() -> None:
    text = read_repo_text("src/nanoleaf_sync/ui/settings_dialog.py")
    assert "self.preview_label.setText(" in text
    assert (
        "self._state.mapping_preview_text()"
        not in text.split("self.preview_label.setText(", 1)[1].split(")", 1)[0]
    )


def test_strip_count_mismatch_warning_text_present() -> None:
    path = "src/nanoleaf_sync/ui/settings_dialog.py"
    assert source_contains_all(
        path,
        "Device-reported count differs from configured count.",
        "The configured manual value is used.",
    )
    normalized = normalized_repo_text(path)
    assert "Changing strip count invalidates calibration." in normalized
    assert "Current anchors were assigned for a different strip length." in normalized
    assert "Use reported count" in normalized
    assert "Keep manual count" in normalized


def test_sdr_white_reference_controls_present() -> None:
    text = read_repo_text("src/nanoleaf_sync/ui/settings_dialog.py")
    assert "Detect KDE SDR white reference" in text
    assert "Use detected value" in text
    assert "sdr_boost_nits_slider.valueChanged.connect(self._on_sdr_white_slider_changed)" in text
    assert "Capture one diagnostic frame" in text
    assert "Export live sampling overlay" in text
    assert "Export synthetic sampling test overlay" in text


def test_fps_slider_label_value_and_tooltip_text() -> None:
    text = read_repo_text("src/nanoleaf_sync/ui/settings_dialog.py")
    assert "Target capture/output FPS" in text
    assert 'self.fps_value.setText(f"{self.fps_slider.value()} FPS")' in text
    assert source_contains_all(
        "src/nanoleaf_sync/ui/settings_dialog.py",
        "This is the target update rate. Actual output FPS may be lower if capture,",
        "processing, or HID output cannot keep up.",
    )
    assert "self.fps_slider.setRange(FPS_MIN, FPS_MAX)" in text
    assert "FPS_MAX = 120" in text
    assert 'grid.addWidget(QLabel("Capture backend"), 0, 0)' in text
    assert "grid.addWidget(self.capture_backend_combo, 0, 1, 1, 2)" in text


def test_slider_readouts_bind_live_value_updates() -> None:
    text = read_repo_text("src/nanoleaf_sync/ui/settings_dialog.py")
    assert "def _bind_live_numeric_updates(self) -> None:" in text
    assert "self.brightness_slider.valueChanged" in text
    assert "self.smoothing_slider.valueChanged" in text
    assert "self.fps_slider.valueChanged" in text
    assert "self.hdr_max_nits_slider.valueChanged" in text
    assert "self.black_luminance_knee_slider.valueChanged" in text
    assert "signal.connect(self._refresh_numeric_labels)" in text


def test_settings_uses_stacked_widget_navigation() -> None:
    text = read_repo_text("src/nanoleaf_sync/ui/settings_dialog.py")
    assert "QStackedWidget()" in text
    assert "on_walk_strip_once=self._walk_strip_once" in text
    assert "def _walk_strip_once(self)" in text


def test_settings_layout_uses_consistent_spacing_helpers() -> None:
    text = read_repo_text("src/nanoleaf_sync/ui/settings_dialog.py")
    assert "def _configure_section_layout(self, layout) -> None:" in text
    assert "def _help_text_label(self, QLabel, text: str):" in text
    assert "self._configure_section_layout(grid)" in text
    assert "self._configure_value_label(label)" in text


def test_guided_led_calibration_controls_present() -> None:
    text = read_repo_text("src/nanoleaf_sync/ui/settings_dialog.py")
    assert "Calibrate LED colour" in text
    assert "Black cutoff" in text
    assert source_contains_all(
        "src/nanoleaf_sync/ui/settings_dialog.py",
        "Neutral luminance: controls how bright grey/white screen areas",
        "appear on the LEDs.",
    )
    assert source_contains_all(
        "src/nanoleaf_sync/ui/led_color_calibration_dialog.py",
        "Reference mode is used for calibration because it avoids saturation boost.",
    )


def test_performance_priority_dropdown_present_and_persisted() -> None:
    text = read_repo_text("src/nanoleaf_sync/ui/settings_dialog.py")
    assert "Performance priority" in text
    assert "performance_priority_combo" in text
    assert "Very high experimental" in read_repo_text("src/nanoleaf_sync/ui/preset_ui.py")
    assert source_contains_all(
        "src/nanoleaf_sync/ui/settings_dialog.py",
        "High priority may improve scheduling consistency. It may fail without permission.",
        "Very high is experimental.",
    )
    assert "performance_priority=value_for_label(" in text
    assert "PERFORMANCE_PRIORITY_LABELS" in text


def test_save_applies_without_closing_dialog() -> None:
    text = read_repo_text("src/nanoleaf_sync/ui/settings_dialog.py")
    assert "QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close" in text
    assert "buttons.accepted.connect(self._apply_settings)" in text
    assert "buttons.rejected.connect(self.reject)" in text
    assert "def _apply_settings(self) -> None:" in text
    assert "updated = self.updated_config()" in text


def test_settings_dialog_surfaces_latest_auto_and_manual_probe_results() -> None:
    text = read_repo_text("src/nanoleaf_sync/ui/settings_dialog.py")
    assert "def _update_latency_label_for_latest_probe_result(self) -> None:" in text
    assert "self._update_latency_label_for_latest_probe_result()" in text
    assert "Last auto-run probe result." in text
    assert "Last manual probe result." in text
    assert "waiting for first result" in text
    assert "Stop mirroring before re-testing backends." in text
    assert "def _update_backend_probe_button_state" in text
    assert "def _backend_probe_blocked_by_runtime_state" in text
    assert "Candidate backends:" in text


def test_sdr_white_preset_changed_uses_defensive_split_parsing() -> None:
    text = read_repo_text("src/nanoleaf_sync/ui/settings_dialog.py")
    assert "contextlib.suppress(ValueError, IndexError)" in text
    assert 'preset_text.split(" ", 1)[0]' in text
