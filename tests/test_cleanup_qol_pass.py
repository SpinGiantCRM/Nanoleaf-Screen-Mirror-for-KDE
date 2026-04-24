from __future__ import annotations

from dataclasses import asdict

import numpy as np

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.normalize import validate_config
from nanoleaf_sync.runtime.edge_locality_diagnostics import run_edge_locality_test
from nanoleaf_sync.runtime.engine import process_frame
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.ui.zone_presets import edge_weighted_layout, make_edge_weighted_zones


def test_active_config_serialization_has_no_legacy_preset_fields() -> None:
    payload = asdict(validate_config(AppConfig()))
    for legacy in ("zone_preset", "edge_sampling_thickness", "color_mode", "hdr_enabled"):
        assert legacy not in payload


def test_first_run_defaults_are_ambient_daily_use() -> None:
    cfg = validate_config(AppConfig())
    assert cfg.layout_preset == "edge_strip"
    assert cfg.edge_locality == "balanced"
    assert cfg.sampling_quality == "high"
    assert cfg.motion_preset == "responsive"
    assert cfg.color_style == "ambient"
    assert cfg.display_preset == "hdr"


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
    layout = edge_weighted_layout(zone_count=zone_count, width=width, height=height, edge_locality="balanced")
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


def test_strip_count_mismatch_warning_exposes_manual_actions() -> None:
    text = open("src/nanoleaf_sync/ui/settings_dialog.py", "r", encoding="utf-8").read()
    assert "Use reported count" in text
    assert "Keep manual count" in text
    assert "Reset anchors and recalibrate" in text


def test_calibration_widget_shows_corner_checklist_and_status() -> None:
    text = open("src/nanoleaf_sync/ui/calibration_widget.py", "r", encoding="utf-8").read()
    assert "corner_checklist_label" in text
    assert "Calibration:" in open("src/nanoleaf_sync/ui/settings_dialog.py", "r", encoding="utf-8").read()


def test_raw_mapping_text_is_diagnostics_only() -> None:
    text = open("src/nanoleaf_sync/ui/settings_dialog.py", "r", encoding="utf-8").read()
    assert "Raw device→source mapping" in text
    assert "self.preview_label.setText(" in text


def test_settings_sections_present() -> None:
    text = open("src/nanoleaf_sync/ui/settings_dialog.py", "r", encoding="utf-8").read()
    for section in ("Display & Color", "Performance", "Calibration", "Device", "Diagnostics"):
        assert section in text
