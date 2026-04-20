from __future__ import annotations

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
