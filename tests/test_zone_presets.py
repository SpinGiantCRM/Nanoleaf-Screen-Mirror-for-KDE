from __future__ import annotations

from nanoleaf_sync.ui.zone_presets import edge_side_counts, make_edge_weighted_zones, make_horizontal_zones


def test_make_horizontal_zones_shape() -> None:
    zones = make_horizontal_zones(4)
    assert len(zones) == 4
    assert zones[0].w == 0.25


def test_make_edge_weighted_zones_shape() -> None:
    zones = make_edge_weighted_zones(8)
    assert len(zones) == 8
    assert all(0.0 <= z.x <= 1.0 and 0.0 <= z.y <= 1.0 for z in zones)


def test_make_edge_weighted_zones_honors_low_counts() -> None:
    zones = make_edge_weighted_zones(1)
    assert len(zones) == 1


def test_make_edge_weighted_zones_stay_perimeter_biased_across_common_counts() -> None:
    for count in (8, 12, 24, 48):
        zones = make_edge_weighted_zones(count)
        assert len(zones) == count
        for zone in zones:
            assert (
                (zone.y == 0.0 and zone.h <= 0.12)
                or (zone.x + zone.w == 1.0 and zone.w <= 0.12)
                or (zone.y + zone.h == 1.0 and zone.h <= 0.12)
                or (zone.x == 0.0 and zone.w <= 0.12)
            )


def test_make_edge_weighted_zones_uses_configured_high_count_thickness() -> None:
    zones = make_edge_weighted_zones(48, edge_sampling_thickness=0.2)
    assert any(zone.w == 0.2 for zone in zones)
    assert any(zone.h == 0.2 for zone in zones)


def test_edge_weighted_side_counts_are_aspect_weighted_for_16_9() -> None:
    top, right, bottom, left = edge_side_counts(zone_count=48, width=1920, height=1080)
    assert top > right
    assert bottom > left
    assert top in {15, 16}
    assert bottom in {15, 16}
    assert right in {8, 9}
    assert left in {8, 9}
    assert top + right + bottom + left == 48


def test_edge_weighted_side_counts_are_balanced_for_square_aspect() -> None:
    top, right, bottom, left = edge_side_counts(zone_count=48, width=1000, height=1000)
    assert max(top, right, bottom, left) - min(top, right, bottom, left) <= 1
    assert top + right + bottom + left == 48


def test_edge_weighted_zone_order_is_continuous_perimeter() -> None:
    zones = make_edge_weighted_zones(48, width=1920, height=1080)
    top, right, bottom, left = edge_side_counts(zone_count=48, width=1920, height=1080)

    bottom_zones = zones[top + right : top + right + bottom]
    assert all(bottom_zones[i].x > bottom_zones[i + 1].x for i in range(len(bottom_zones) - 1))

    left_zones = zones[top + right + bottom :]
    assert len(left_zones) == left
    assert all(left_zones[i].y > left_zones[i + 1].y for i in range(len(left_zones) - 1))
