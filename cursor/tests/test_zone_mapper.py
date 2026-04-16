from __future__ import annotations

from nanoleaf_sync.processing.zone_mapper import map_colors_to_device_zones


def test_zone_mapper_offset_rotation() -> None:
    screen = [(10, 0, 0), (20, 0, 0), (30, 0, 0)]
    out = map_colors_to_device_zones(
        screen, device_zone_count=3, zone_offset=1, reverse=False
    )
    assert out == [(20, 0, 0), (30, 0, 0), (10, 0, 0)]


def test_zone_mapper_reverse() -> None:
    screen = [(10, 0, 0), (20, 0, 0), (30, 0, 0)]
    out = map_colors_to_device_zones(
        screen, device_zone_count=3, zone_offset=0, reverse=True
    )
    # device0 picks src[2], device1 src[1], device2 src[0]
    assert out == [(30, 0, 0), (20, 0, 0), (10, 0, 0)]


def test_zone_mapper_explicit_map() -> None:
    screen = [(10, 0, 0), (20, 0, 0), (30, 0, 0)]
    out = map_colors_to_device_zones(
        screen, device_zone_count=2, explicit_zone_map=[2, 0]
    )
    assert out == [(30, 0, 0), (10, 0, 0)]

    # If explicit map is shorter than device zone count, remaining zones use src[0]
    out2 = map_colors_to_device_zones(
        screen, device_zone_count=4, explicit_zone_map=[2, 0]
    )
    assert out2 == [(30, 0, 0), (10, 0, 0), (10, 0, 0), (10, 0, 0)]
