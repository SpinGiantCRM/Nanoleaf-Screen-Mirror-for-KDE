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
    count = max(1, int(zone_count))
    edge_thickness = 0.16

    per_side = count // 4
    remainder = count % 4
    side_counts = [per_side, per_side, per_side, per_side]
    for side_idx in range(remainder):
        side_counts[side_idx] += 1

    zones: List[ZoneConfig] = []
    top_n, right_n, bottom_n, left_n = side_counts

    for i in range(top_n):
        zones.append(ZoneConfig(x=i / top_n, y=0.0, w=1.0 / top_n, h=edge_thickness))
    for i in range(right_n):
        zones.append(ZoneConfig(x=1.0 - edge_thickness, y=i / right_n, w=edge_thickness, h=1.0 / right_n))
    for i in range(bottom_n):
        zones.append(ZoneConfig(x=i / bottom_n, y=1.0 - edge_thickness, w=1.0 / bottom_n, h=edge_thickness))
    for i in range(left_n):
        zones.append(ZoneConfig(x=0.0, y=i / left_n, w=edge_thickness, h=1.0 / left_n))
    return zones[:count]
