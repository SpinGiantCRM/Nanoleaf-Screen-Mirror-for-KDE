"""Headless UI contract tests: settings widgets write expected AppConfig fields."""

from __future__ import annotations

from dataclasses import fields

from nanoleaf_sync.config.model import AppConfig, PrivacyZone
from nanoleaf_sync.ui.preset_ui import DISPLAY_PRESET_LABELS, label_for_value
from tests.qt_headless import make_settings_dialog

# Config fields intentionally not surfaced in Settings (internal / pipeline-only).
INTERNAL_CONFIG_FIELDS = frozenset(
    {
        "schema_version",
        "privacy_zones",  # edited via list UI, not 1:1 field widget
        "virtual_zone_oversample",
        "scene_adaptive_profiles",
        "zone_temporal_accumulation",
        "blue_noise_dither",
        "zone_box_filter_sampling",
        "multi_moment_zone_colors",
        "custom_gamut_red_x",
        "custom_gamut_red_y",
        "custom_gamut_green_x",
        "custom_gamut_green_y",
        "custom_gamut_blue_x",
        "custom_gamut_blue_y",
        "wizard_in_progress_state",
        "wizard_state_version",
        "auto_selected_backend",
        "auto_probe_signature",
        "auto_probe_timestamp",
        "latency_last_backend",
        "latency_last_value_ms",
        "latency_last_trigger",
        "latency_last_timestamp",
        "device_zone_count_raw",
        "calibration_schema_version",
        "source_side_counts",
        "zones",
        "led_calibration_profile_sdr",
        "led_calibration_profile_hdr",
        "calibration",
        "corner_anchor_top_left",
        "corner_anchor_top_right",
        "corner_anchor_bottom_right",
        "corner_anchor_bottom_left",
        "calibration_model",
        "reverse_zones",
        "output_channel_order",
    }
)

USER_FACING_CONFIG_FIELDS = (
    frozenset(field.name for field in fields(AppConfig)) - INTERNAL_CONFIG_FIELDS
)


def test_default_display_preset_matches_app_config(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    assert widget._active_display_preset == AppConfig.display_preset


def test_four_d_sync_checkbox_maps_to_sync_mode(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    widget.four_d_sync_checkbox.setChecked(True)
    assert widget.updated_config().sync_mode == "4d"
    widget.four_d_sync_checkbox.setChecked(False)
    assert widget.updated_config().sync_mode == "standard"


def test_display_preset_combo_maps_to_config(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    widget.display_preset_combo.setCurrentIndex(max(0, widget.display_preset_combo.findText("SDR")))
    widget._on_display_preset_changed()
    assert widget.updated_config().display_preset == "sdr"


def test_display_gamut_combo_excludes_custom(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    combo = widget.display_gamut_combo
    items = [combo.itemText(i) for i in range(combo.count())]
    assert "Custom" not in items


def test_privacy_zones_round_trip_through_settings(monkeypatch) -> None:
    cfg = AppConfig(privacy_zones=[PrivacyZone(x=0.0, y=0.9, w=1.0, h=0.1)])
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch, cfg=cfg)
    assert widget.privacy_zones_list.count() == 1
    widget.privacy_zone_x_edit.setText("0.85")
    widget.privacy_zone_y_edit.setText("0.0")
    widget.privacy_zone_w_edit.setText("0.15")
    widget.privacy_zone_h_edit.setText("0.12")
    widget._add_privacy_zone()
    out = widget.updated_config()
    assert len(out.privacy_zones) == 2
    assert out.privacy_zones[1].x == 0.85


def test_settings_exposes_core_user_facing_widgets(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    expected_widgets = {
        "brightness": "brightness_slider",
        "smoothing": "smoothing_slider",
        "fps": "fps_slider",
        "display_preset": "display_preset_combo",
        "sync_mode": "four_d_sync_checkbox",
        "prefer_backend": "capture_backend_combo",
        "capture_monitor": "capture_monitor_edit",
        "display_gamut": "display_gamut_combo",
        "motion_preset": "motion_preset_combo",
        "color_style": "color_style_combo",
        "edge_locality": "edge_locality_combo",
        "device_zone_count": "device_zone_count_slider",
    }
    for _field, attr in expected_widgets.items():
        assert hasattr(widget, attr), f"missing widget for {attr}"


def test_settings_dialog_shows_auto_display_preset_for_fresh_config(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    expected = label_for_value(DISPLAY_PRESET_LABELS, AppConfig.display_preset, default="Auto")
    assert widget.display_preset_combo.currentText() == expected


def test_internal_pipeline_fields_not_in_settings_combos(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    combo_text = " ".join(
        widget.display_gamut_combo.itemText(i) for i in range(widget.display_gamut_combo.count())
    ).lower()
    assert "scene adaptive" not in combo_text
    assert "privacy" not in combo_text  # separate section, not a stray combo label
