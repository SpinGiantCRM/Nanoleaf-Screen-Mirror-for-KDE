from __future__ import annotations

from typing import List

from nanoleaf_sync.config.model import ZoneConfig


def make_horizontal_zones(zone_count: int) -> List[ZoneConfig]:
    """
    Build zone rectangles spanning the screen horizontally.

    All zones cover full height and are equal-width segments.
    """

    count = max(1, int(zone_count))
    zones: List[ZoneConfig] = []
    for i in range(count):
        zones.append(
            ZoneConfig(
                x=i / count,
                y=0.0,
                w=1.0 / count,
                h=1.0,
            )
        )
    return zones


def make_edge_weighted_zones(zone_count: int) -> List[ZoneConfig]:
    """
    Build edge-biased zones prioritizing top/left/right/bottom edges.

    Layout:
    - top edge strip (first quarter)
    - right edge strip (second quarter)
    - bottom edge strip (third quarter)
    - left edge strip (fourth quarter)
    """
    count = max(4, int(zone_count))
    edge_thickness = 0.16
    per_side = max(1, count // 4)

    zones: List[ZoneConfig] = []
    for i in range(per_side):
        zones.append(ZoneConfig(x=i / per_side, y=0.0, w=1.0 / per_side, h=edge_thickness))
    for i in range(per_side):
        zones.append(ZoneConfig(x=1.0 - edge_thickness, y=i / per_side, w=edge_thickness, h=1.0 / per_side))
    for i in range(per_side):
        zones.append(ZoneConfig(x=i / per_side, y=1.0 - edge_thickness, w=1.0 / per_side, h=edge_thickness))
    for i in range(per_side):
        zones.append(ZoneConfig(x=0.0, y=i / per_side, w=edge_thickness, h=1.0 / per_side))
    return zones[:count]
