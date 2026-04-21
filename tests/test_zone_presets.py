from __future__ import annotations

from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones, make_horizontal_zones


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
