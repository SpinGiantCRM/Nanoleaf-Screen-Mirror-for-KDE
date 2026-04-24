from __future__ import annotations

from nanoleaf_sync.ui.calibration_flow import derive_corner_anchor_device_indices
from nanoleaf_sync.ui.calibration_preview import calibration_test_frame, corner_anchor_steps


def test_derive_corner_anchor_device_indices_stays_unique_with_more_device_zones() -> None:
    anchors = derive_corner_anchor_device_indices(
        zone_count=8,
        device_zone_count=24,
        zone_offset=3,
        reverse_zones=False,
    )
    assert len(anchors) == 4
    assert len(set(anchors)) == 4


def test_derive_corner_anchor_device_indices_limits_to_available_device_zones() -> None:
    anchors = derive_corner_anchor_device_indices(
        zone_count=12,
        device_zone_count=2,
        zone_offset=0,
        reverse_zones=False,
    )
    assert anchors == [0, 1]


def test_corner_anchor_derivation_is_deterministic_for_same_inputs() -> None:
    params = {
        "zone_count": 20,
        "device_zone_count": 24,
        "zone_offset": -7,
        "reverse_zones": True,
    }
    first = derive_corner_anchor_device_indices(**params)
    second = derive_corner_anchor_device_indices(**params)
    third = derive_corner_anchor_device_indices(**params)
    assert first == second == third


def test_corner_anchor_derivation_changes_with_offset_and_reverse_orientation() -> None:
    default = derive_corner_anchor_device_indices(
        zone_count=16,
        device_zone_count=16,
        zone_offset=0,
        reverse_zones=False,
    )
    shifted = derive_corner_anchor_device_indices(
        zone_count=16,
        device_zone_count=16,
        zone_offset=3,
        reverse_zones=False,
    )
    reversed_shifted = derive_corner_anchor_device_indices(
        zone_count=16,
        device_zone_count=16,
        zone_offset=3,
        reverse_zones=True,
    )
    assert shifted != default
    assert reversed_shifted != shifted


def test_corner_anchor_derivation_honors_explicit_start_anchor() -> None:
    anchors = derive_corner_anchor_device_indices(
        zone_count=12,
        device_zone_count=12,
        zone_offset=0,
        reverse_zones=False,
        start_anchor=5,
    )
    assert anchors[0] == 5


def test_calibration_test_frame_never_truncates_device_zone_count() -> None:
    frame = calibration_test_frame(device_zone_count=24, active_indices=[23])
    assert len(frame) == 24
    assert frame[-1] != (0, 0, 0)


def test_corner_anchor_steps_use_top_left_top_right_bottom_right_bottom_left_order() -> None:
    steps = corner_anchor_steps(
        zone_count=8,
        device_zone_count=8,
        zone_offset=0,
        reverse_zones=False,
    )
    labels = [step.label for step in steps]
    assert "top-left" in labels[0]
    assert "top-right" in labels[1]
    assert "bottom-right" in labels[2]
    assert "bottom-left" in labels[3]
