from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

RGBTuple = Tuple[int, int, int]


def _normalized_corner_offsets(corner_zone_offsets: Optional[Sequence[int]]) -> tuple[int, int, int, int] | None:
    if not corner_zone_offsets:
        return None
    padded = [int(v) for v in list(corner_zone_offsets)[:4]]
    while len(padded) < 4:
        padded.append(0)
    if not any(padded):
        return None
    return tuple(padded)


def _interpolated_corner_adjustment(
    *,
    device_index: int,
    device_zone_count: int,
    corner_zone_offsets: tuple[int, int, int, int],
) -> int:
    total = max(1, int(device_zone_count))
    if total <= 1:
        return int(corner_zone_offsets[0])

    quarter = max(1.0, total / 4.0)
    pos = float(int(device_index) % total)
    segment = int(pos // quarter) % 4
    next_segment = (segment + 1) % 4
    local_start = segment * quarter
    t = max(0.0, min(1.0, (pos - local_start) / quarter))
    start = float(corner_zone_offsets[segment])
    end = float(corner_zone_offsets[next_segment])
    return int(round(start + (end - start) * t))


def resolve_device_zone_indices(
    source_zone_count: int,
    *,
    device_zone_count: int,
    zone_offset: int = 0,
    reverse: bool = False,
    explicit_zone_map: Optional[Sequence[int]] = None,
    corner_zone_offsets: Optional[Sequence[int]] = None,
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
    normalized_corner_offsets = _normalized_corner_offsets(corner_zone_offsets)
    for device_idx in range(dst_n):
        src_idx = device_idx + int(zone_offset)
        if reverse:
            src_idx = (src_n - 1) - src_idx
        if normalized_corner_offsets is not None:
            src_idx += _interpolated_corner_adjustment(
                device_index=device_idx,
                device_zone_count=dst_n,
                corner_zone_offsets=normalized_corner_offsets,
            )
        out.append(src_idx % src_n)
    return out


def map_colors_to_device_zones(
    screen_colors: Sequence[RGBTuple],
    *,
    device_zone_count: int,
    zone_offset: int = 0,
    reverse: bool = False,
    explicit_zone_map: Optional[Sequence[int]] = None,
    corner_zone_offsets: Optional[Sequence[int]] = None,
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
        corner_zone_offsets=corner_zone_offsets,
    )
    return [src[idx] for idx in mapping]
