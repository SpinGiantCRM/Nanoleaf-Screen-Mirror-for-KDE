from __future__ import annotations

from nanoleaf_sync.ui.calibration_flow import derive_corner_anchor_device_indices
from nanoleaf_sync.ui.calibration_preview import (
    calibration_test_frame,
    corner_anchor_steps,
    coverage_sanity_step,
    single_zone_step,
)
from nanoleaf_sync.ui.zone_calibration import (
    corner_anchor_validation_summary,
    mapping_snapshot_from_config,
    mapping_preview_text,
    mapping_preview_visual,
    zone_test_instruction,
)
from nanoleaf_sync.config.model import AppConfig


def test_mapping_preview_visual_reflects_reverse_and_offset() -> None:
    normal = mapping_preview_visual(
        zone_count=4,
        device_zone_count=4,
        zone_offset=0,
        reverse_zones=False,
    )
    reversed_with_offset = mapping_preview_visual(
        zone_count=4,
        device_zone_count=4,
        zone_offset=1,
        reverse_zones=True,
    )
    assert normal != reversed_with_offset
    assert "[D0→S0]" in normal


def test_mapping_preview_text_mentions_corner_refinement_when_enabled() -> None:
    text = mapping_preview_visual(
        zone_count=8,
        device_zone_count=8,
        zone_offset=0,
        reverse_zones=False,
        corner_zone_offsets=[1, 0, -1, 0],
    )
    assert "D0" in text


def test_mapping_preview_text_waits_for_device_zone_count_in_auto_mode() -> None:
    text = mapping_preview_text(
        zone_count=8,
        device_zone_count=0,
        zone_offset=0,
        reverse_zones=False,
        corner_anchor_top_left=0,
        corner_anchor_top_right=2,
        corner_anchor_bottom_right=4,
        corner_anchor_bottom_left=6,
        calibration_model="corner_anchored",
    )
    assert "strip zones: 0" in text
    assert "Corner anchor validation:" in text
    assert "Anchor validation summary:" in text


def test_corner_anchor_validation_summary_reports_missing_duplicate_and_out_of_range() -> None:
    summary = corner_anchor_validation_summary(
        device_zone_count=8,
        corner_anchor_top_left=-1,
        corner_anchor_top_right=3,
        corner_anchor_bottom_right=3,
        corner_anchor_bottom_left=10,
    )
    assert "missing corners: TL" in summary
    assert "duplicate zone assignments: 3 (TR/BR)" in summary
    assert "out-of-range assignments: BL=10" in summary


def test_zone_test_instruction_wraps_steps() -> None:
    assert zone_test_instruction(step=5, total=4).endswith("#2 now.")


def test_calibration_test_frame_only_lights_active_zone() -> None:
    frame = calibration_test_frame(device_zone_count=5, active_indices=[3], active_color=(10, 20, 30))
    assert frame == [(0, 0, 0), (0, 0, 0), (0, 0, 0), (10, 20, 30), (0, 0, 0)]


def test_corner_anchor_steps_are_labeled() -> None:
    anchors = corner_anchor_steps(
        zone_count=12,
        device_zone_count=12,
        zone_offset=0,
        reverse_zones=False,
    )
    assert len(anchors) == 4
    assert "top-left" in anchors[0].label


def test_single_zone_step_reflects_offset_and_reverse() -> None:
    step = single_zone_step(
        step=0,
        zone_count=4,
        device_zone_count=4,
        zone_offset=1,
        reverse_zones=True,
    )
    assert step.device_zone_index == 0
    assert step.source_zone_index != 0


def test_coverage_sanity_label_includes_progress() -> None:
    step = coverage_sanity_step(
        step=2,
        zone_count=8,
        device_zone_count=8,
        zone_offset=0,
        reverse_zones=False,
    )
    assert "zone 3/8 active" in step.label


def test_corner_anchor_derivation_uses_mapping() -> None:
    anchors = derive_corner_anchor_device_indices(
        zone_count=8,
        device_zone_count=8,
        zone_offset=2,
        reverse_zones=True,
    )
    assert len(anchors) == 4
    assert len(set(anchors)) == 4


def test_calibration_test_frame_supports_brightness_scaling() -> None:
    frame = calibration_test_frame(
        device_zone_count=3,
        active_indices=[1],
        active_color=(100, 80, 60),
        brightness=0.5,
    )
    assert frame[1] == (50, 40, 30)


def test_mapping_snapshot_from_config_uses_nested_calibration_payload() -> None:
    cfg = AppConfig(zone_offset=0, device_zone_count=8)
    cfg.calibration.calibration_model = "corner_anchored"
    cfg.calibration.device_zone_count = 8
    cfg.calibration.corner_anchor_top_left = 0
    cfg.calibration.corner_anchor_top_right = 2
    cfg.calibration.corner_anchor_bottom_right = 4
    cfg.calibration.corner_anchor_bottom_left = 6

    snapshot = mapping_snapshot_from_config(config=cfg, source_zone_count=8)
    assert snapshot.strategy == "corner_anchored"


def test_mapping_preview_corner_anchor_validation_handles_all_missing() -> None:
    text = mapping_preview_text(
        zone_count=8,
        device_zone_count=8,
        zone_offset=0,
        reverse_zones=False,
        calibration_model="corner_anchored",
        corner_anchor_top_left=-1,
        corner_anchor_top_right=-1,
        corner_anchor_bottom_right=-1,
        corner_anchor_bottom_left=-1,
    )
    assert "Corner anchor validation:" in text
    assert "missing" in text.lower()


def test_mapping_preview_corner_anchor_resolution_is_deterministic() -> None:
    kwargs = {
        "zone_count": 12,
        "device_zone_count": 12,
        "calibration_model": "corner_anchored",
        "corner_anchor_top_left": 0,
        "corner_anchor_top_right": 3,
        "corner_anchor_bottom_right": 6,
        "corner_anchor_bottom_left": 9,
        "zone_offset": 2,
        "reverse_zones": True,
    }
    first = mapping_preview_visual(**kwargs)
    second = mapping_preview_visual(**kwargs)
    assert first == second
