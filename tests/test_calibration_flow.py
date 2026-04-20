from __future__ import annotations

from nanoleaf_sync.ui.calibration_flow import CALIBRATION_SEQUENCE, calibration_sequence_text, derive_corner_anchor_device_indices
from nanoleaf_sync.ui.calibration_preview import calibration_test_frame


def test_calibration_sequence_contains_required_order() -> None:
    keys = [step.key for step in CALIBRATION_SEQUENCE]
    assert keys == [
        "coverage-sanity",
        "start-point",
        "direction-walk",
        "corner-anchors",
        "fine-offset",
        "manual-remap",
    ]
    assert "Coverage sanity" in calibration_sequence_text()


def test_derive_corner_anchor_device_indices_stays_unique_with_more_device_zones() -> None:
    anchors = derive_corner_anchor_device_indices(
        zone_count=8,
        device_zone_count=24,
        zone_offset=3,
        reverse_zones=False,
    )
    assert len(anchors) == 4
    assert len(set(anchors)) == 4


def test_calibration_test_frame_never_truncates_device_zone_count() -> None:
    frame = calibration_test_frame(device_zone_count=24, active_indices=[23])
    assert len(frame) == 24
    assert frame[-1] != (0, 0, 0)


def test_derive_corner_anchor_device_indices_limits_to_unique_device_zones() -> None:
    anchors = derive_corner_anchor_device_indices(
        zone_count=12,
        device_zone_count=2,
        zone_offset=0,
        reverse_zones=False,
    )
    assert anchors == [0, 1]
