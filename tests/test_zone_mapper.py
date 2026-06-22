from nanoleaf_sync.color.zone_mapper import map_colors_to_device_zones, resolve_device_zone_indices


def test_zone_mapper_basic_forward_and_reverse() -> None:
    assert resolve_device_zone_indices(4, device_zone_count=4) == [0, 1, 2, 3]
    assert resolve_device_zone_indices(4, device_zone_count=4, reverse=True) == [3, 2, 1, 0]


def test_zone_mapper_respects_explicit_map_when_enabled() -> None:
    assert resolve_device_zone_indices(
        4,
        device_zone_count=4,
        fixed_mapping=[2, 1, 0, 3],
    ) == [2, 1, 0, 3]


def test_map_colors_to_device_zones() -> None:
    screen = [(10, 0, 0), (20, 0, 0), (30, 0, 0)]
    assert map_colors_to_device_zones(screen, device_zone_count=3) == screen


def test_reverse_applied_with_fixed_mapping() -> None:
    mapping = [0, 10, 20, 30]
    forward = resolve_device_zone_indices(
        48,
        device_zone_count=4,
        reverse=False,
        fixed_mapping=mapping,
    )
    reversed_map = resolve_device_zone_indices(
        48,
        device_zone_count=4,
        reverse=True,
        fixed_mapping=mapping,
    )
    assert forward == mapping
    assert reversed_map == list(reversed(mapping))
