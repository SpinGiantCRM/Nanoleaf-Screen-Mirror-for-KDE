from __future__ import annotations

from nanoleaf_sync.ui.zone_presets import (
    edge_side_counts,
    make_edge_weighted_zones,
    make_horizontal_zones,
)


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


def test_tight_locality_is_narrower_than_wide() -> None:
    tight = make_edge_weighted_zones(48, edge_locality="tight")
    wide = make_edge_weighted_zones(48, edge_locality="wide")
    assert max(min(z.w, z.h) for z in tight) < max(min(z.w, z.h) for z in wide)


def test_edge_weighted_side_counts_are_aspect_weighted_for_16_9() -> None:
    top, right, bottom, left = edge_side_counts(zone_count=48, width=1920, height=1080)
    assert top > right
    assert bottom > left
    assert top + right + bottom + left == 48


def test_edge_weighted_zone_order_is_continuous_perimeter() -> None:
    zones = make_edge_weighted_zones(48, width=1920, height=1080)
    top, right, bottom, left = edge_side_counts(zone_count=48, width=1920, height=1080)

    bottom_zones = zones[top + right : top + right + bottom]
    assert all(bottom_zones[i].x > bottom_zones[i + 1].x for i in range(len(bottom_zones) - 1))

    left_zones = zones[top + right + bottom :]
    assert len(left_zones) == left
    assert all(left_zones[i].y > left_zones[i + 1].y for i in range(len(left_zones) - 1))
