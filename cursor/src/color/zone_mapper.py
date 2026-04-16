from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

RGBTuple = Tuple[int, int, int]


def resolve_device_zone_indices(
    source_zone_count: int,
    *,
    device_zone_count: int,
    zone_offset: int = 0,
    reverse: bool = False,
    explicit_zone_map: Optional[Sequence[int]] = None,
) -> List[int]:
    src_n = max(0, int(source_zone_count))
    dst_n = max(0, int(device_zone_count))

    if src_n == 0 or dst_n == 0:
        return []

    if explicit_zone_map:
        out: List[int] = []
        for i in range(dst_n):
            if i < len(explicit_zone_map):
                out.append(int(explicit_zone_map[i]) % src_n)
            else:
                out.append(0)
        return out

    out: List[int] = []
    for device_idx in range(dst_n):
        src_idx = device_idx + int(zone_offset)
        if reverse:
            src_idx = (src_n - 1) - src_idx
        out.append(src_idx % src_n)
    return out


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
      indexes a screen color (protocol-compatible with the official app's
      "zone order" concept).
    """

    src = list(screen_colors)
    if not src:
        return [(0, 0, 0)] * max(0, int(device_zone_count))

    mapping = resolve_device_zone_indices(
        len(src),
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse=reverse,
        explicit_zone_map=explicit_zone_map,
    )
    return [src[idx] for idx in mapping]
