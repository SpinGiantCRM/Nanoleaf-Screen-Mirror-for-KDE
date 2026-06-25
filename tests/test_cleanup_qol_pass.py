from __future__ import annotations

from dataclasses import asdict

import numpy as np

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.normalize import validate_config
from nanoleaf_sync.runtime.color_pipeline import ColorPipelineParams
from nanoleaf_sync.runtime.edge_locality_diagnostics import run_edge_locality_test
from nanoleaf_sync.runtime.engine import _make_fps_governor, process_frame
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.runtime.readiness_check import run_readiness_check
from nanoleaf_sync.ui.settings_dialog import SETTINGS_SECTIONS
from nanoleaf_sync.ui.tray_app import _tray_icon_fallback_candidates
from nanoleaf_sync.ui.zone_presets import edge_weighted_layout, make_edge_weighted_zones
from tests.qt_headless import (
    button_texts,
    make_display_configurator,
    make_settings_dialog,
)


def test_active_config_serialization_has_no_legacy_preset_fields() -> None:
    payload = asdict(validate_config(AppConfig()))
    for legacy in ("zone_preset", "edge_sampling_thickness", "color_mode", "hdr_enabled"):
        assert legacy not in payload


def test_first_run_defaults_are_ambient_daily_use() -> None:
    cfg = validate_config(AppConfig())
    assert cfg.layout_preset == "edge_strip"
    assert cfg.edge_locality == "balanced"
    assert cfg.performance_profile == "balanced"
    assert cfg.sampling_quality == "balanced"
    assert cfg.fps == 60
    assert cfg.motion_preset == "responsive"
    assert cfg.color_style == "ambient"
    assert cfg.display_preset == "sdr"
    assert cfg.hdr_transfer == "srgb"
    assert cfg.hdr_primaries == "bt709"


def test_runtime_and_ui_fallbacks_match_balanced_profile_defaults(monkeypatch) -> None:
    cfg = validate_config(AppConfig())
    assert ColorPipelineParams().sampling_quality == cfg.sampling_quality

    readiness = run_readiness_check(config=cfg, runtime_status={})
    assert readiness is not None

    governor = _make_fps_governor(cfg)
    assert governor.target_fps == cfg.fps

    _qt, _app, _settings_dialog, settings = make_settings_dialog(monkeypatch)
    _qt2, _app2, _wizard_dialog, wizard = make_display_configurator(monkeypatch)
    assert settings.edge_locality_combo.currentText() == "Balanced"
    assert settings.sampling_quality_combo.currentText() == "Balanced"
    assert wizard.edge_locality_combo.currentText() == "Balanced"
    assert wizard.sampling_quality_combo.currentText() == "Balanced"
    assert settings.updated_config().hdr_transfer == "srgb"
    assert settings.updated_config().hdr_primaries == "bt709"


def test_reference_mode_preserves_locality_for_bottom_left_signal() -> None:
    zone_count = 48
    width, height = 320, 180
    zones = make_edge_weighted_zones(zone_count, width=width, height=height, edge_locality="tight")
    zones_px = zones_from_config(zones, width=width, height=height)
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    patch = 14
    frame[height - patch :, :patch, 1] = 255

    colors = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=list(range(zone_count)),
        brightness=1.0,
        smoothing=1.0,
        edge_locality="balanced",
        motion_preset="responsive",
        color_style="reference",
    )
    arr = np.asarray(colors, dtype=np.uint8)
    layout = edge_weighted_layout(
        zone_count=zone_count, width=width, height=height, edge_locality="balanced"
    )
    top_n, right_n, bottom_n, _left_n = layout.side_counts
    bottom_start = top_n + right_n
    far_right_bottom = arr[bottom_start : bottom_start + max(1, bottom_n // 2), 1]
    assert float(far_right_bottom.mean()) < 20.0


def test_edge_locality_diagnostic_corner_test_passes() -> None:
    result = run_edge_locality_test(
        zone_count=48,
        edge_locality="balanced",
        sampling_quality="high",
        motion_preset="responsive",
        color_style="ambient",
    )
    assert result.far_edge_zones_stayed_dark is True
    assert "far_edge_dark=yes" in result.summary


def test_strip_count_mismatch_warning_exposes_manual_actions(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    buttons = button_texts(widget, _qt)
    assert "Use reported count" in buttons
    assert "Keep manual count" in buttons
    assert "Reset anchors and recalibrate" in buttons


def test_calibration_widget_shows_corner_checklist_and_status(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    assert hasattr(widget.simple_calibration_widget, "corner_checklist_label")
    widget._refresh_preview_label()
    assert "Calibration:" in widget.simple_calibration_widget.validation_label.text()


def test_raw_mapping_text_is_diagnostics_only(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    widget._refresh_preview_label()
    assert "Raw device→source mapping" in widget.diagnostics_mapping_label.text()
    assert "Raw device→source mapping" not in widget.preview_label.text()


def test_settings_sections_present(monkeypatch) -> None:
    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    nav_sections = [widget._section_nav.item(i).text() for i in range(widget._section_nav.count())]
    for section in ("Everyday", "Strip setup", "Fine-tuning", "Colour", "Advanced"):
        assert section in nav_sections
    assert nav_sections == list(SETTINGS_SECTIONS)


def test_tray_icon_fallback_checks_packaged_assets_before_checkout_assets() -> None:
    candidates = _tray_icon_fallback_candidates()
    assert len(candidates) >= 2
    package_root = str(candidates[0])
    checkout_root = str(candidates[1])
    assert package_root.endswith("nanoleaf-kde-sync.svg")
    assert checkout_root.endswith("nanoleaf-kde-sync.svg")
    assert "assets" in package_root
    assert "assets" in checkout_root


def test_pipeline_setup_has_no_dead_fps_expression() -> None:
    cfg = validate_config(AppConfig(fps=30))
    governor = _make_fps_governor(cfg)
    assert governor.target_fps == 30
