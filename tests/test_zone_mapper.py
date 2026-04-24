from nanoleaf_sync.color.zone_mapper import map_colors_to_device_zones, resolve_device_zone_indices


def test_zone_mapper_basic_forward_and_reverse() -> None:
    assert resolve_device_zone_indices(4, device_zone_count=4) == [0, 1, 2, 3]
    assert resolve_device_zone_indices(4, device_zone_count=4, reverse=True) == [3, 2, 1, 0]


def test_zone_mapper_respects_explicit_map_when_enabled() -> None:
    assert resolve_device_zone_indices(
        4,
        device_zone_count=4,
        manual_mapping_enabled=True,
        explicit_zone_map=[2, 1, 0, 3],
    ) == [2, 1, 0, 3]


def test_map_colors_to_device_zones() -> None:
    screen = [(10, 0, 0), (20, 0, 0), (30, 0, 0)]
    assert map_colors_to_device_zones(screen, device_zone_count=3) == screen
