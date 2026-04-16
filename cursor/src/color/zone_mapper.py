from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

RGBTuple = Tuple[int, int, int]


def map_colors_to_device_zones(
    screen_colors: Sequence[RGBTuple],
    *,
    device_zone_count: int,
    zone_offset: int = 0,
    reverse: bool = False,
    explicit_zone_map: Optional[Sequence[int]] = None,
) -> List[RGBTuple]:
    """
    Map sampled screen-zone colors to physical Nanoleaf device zones.

    Calibration requirements:
    - `zone_offset` rotates mapping so the correct screen region lands on
      the correct physical segment.
    - `reverse` flips orientation.
    - `explicit_zone_map` allows fully custom mapping where each device zone
      indexes a screen color (protocol-compatible with the official app’s
      "zone order" concept).
    """

    src = list(screen_colors)
    if not src:
        return [(0, 0, 0)] * max(0, int(device_zone_count))

    src_n = len(src)
    dst_n = max(0, int(device_zone_count))

    if dst_n == 0:
        return []

    if explicit_zone_map:
        # Clamp explicit map indexes and respec dst length.
        out: List[RGBTuple] = []
        for i in range(dst_n):
            if i < len(explicit_zone_map):
                idx = int(explicit_zone_map[i])
                idx = idx % src_n
                out.append(src[idx])
            else:
                out.append(src[0])
        return out

    # Apply circular shift and optional reverse.
    out: List[RGBTuple] = []
    for device_idx in range(dst_n):
        src_idx = device_idx + int(zone_offset)
        if reverse:
            src_idx = (src_n - 1) - src_idx
        src_idx = src_idx % src_n
        out.append(src[src_idx])
    return out
