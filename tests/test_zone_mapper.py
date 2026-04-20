from __future__ import annotations

from nanoleaf_sync.color.zone_mapper import map_colors_to_device_zones


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


def test_zone_mapper_wraps_large_positive_offset() -> None:
    screen = [(10, 0, 0), (20, 0, 0), (30, 0, 0)]
    out = map_colors_to_device_zones(screen, device_zone_count=3, zone_offset=10)
    assert out == [(20, 0, 0), (30, 0, 0), (10, 0, 0)]


def test_zone_mapper_supports_per_corner_refinement() -> None:
    screen = [(i, 0, 0) for i in range(8)]
    out = map_colors_to_device_zones(
        screen,
        device_zone_count=8,
        zone_offset=0,
        corner_zone_offsets=[1, 0, -1, 0],
    )
    # Corners shift independently; output should differ from identity map.
    assert out != screen
    assert out[0][0] == 1
    assert out[4][0] == 3


def test_zone_mapper_corner_adjustments_stay_local_to_each_corner() -> None:
    screen = [(i, 0, 0) for i in range(16)]
    base = map_colors_to_device_zones(screen, device_zone_count=16, zone_offset=0, corner_zone_offsets=[0, 0, 0, 0])
    top_left_shifted = map_colors_to_device_zones(screen, device_zone_count=16, zone_offset=0, corner_zone_offsets=[3, 0, 0, 0])

    # The nearest corner changes predictably.
    assert top_left_shifted[0][0] != base[0][0]
    # Opposite corner remains stable when only TL is tuned.
    assert top_left_shifted[8][0] == base[8][0]
    # Neighboring side center should remain stable too.
    assert top_left_shifted[4][0] == base[4][0]
