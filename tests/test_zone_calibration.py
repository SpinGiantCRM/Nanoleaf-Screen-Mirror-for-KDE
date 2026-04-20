from __future__ import annotations

from nanoleaf_sync.ui.calibration_preview import calibration_test_frame, corner_anchor_steps, single_zone_step
from nanoleaf_sync.ui.zone_calibration import mapping_preview_visual, zone_test_instruction


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


def test_zone_test_instruction_wraps_steps() -> None:
    assert zone_test_instruction(step=5, total=4).endswith("#2 now.")


def test_calibration_test_frame_only_lights_active_zone() -> None:
    frame = calibration_test_frame(device_zone_count=5, active_indices=[3], active_color=(10, 20, 30))
    assert frame == [(0, 0, 0), (0, 0, 0), (0, 0, 0), (10, 20, 30), (0, 0, 0)]


def test_corner_anchor_steps_are_labeled() -> None:
    anchors = corner_anchor_steps(device_zone_count=12)
    assert [a.label for a in anchors] == [
        "Corner anchor: top-left",
        "Corner anchor: top-right",
        "Corner anchor: bottom-right",
        "Corner anchor: bottom-left",
    ]


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
