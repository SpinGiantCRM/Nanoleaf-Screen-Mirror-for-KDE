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
