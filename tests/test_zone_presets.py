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
