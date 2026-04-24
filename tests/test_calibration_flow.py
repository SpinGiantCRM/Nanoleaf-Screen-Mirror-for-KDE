from nanoleaf_sync.ui.calibration_flow import derive_corner_anchor_device_indices


def test_corner_anchor_indices_are_deterministic() -> None:
    first = derive_corner_anchor_device_indices(zone_count=16, device_zone_count=16, reverse_zones=False)
    second = derive_corner_anchor_device_indices(zone_count=16, device_zone_count=16, reverse_zones=False)
    assert first == second
    assert len(first) == 4
