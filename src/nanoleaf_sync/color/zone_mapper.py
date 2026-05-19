from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from nanoleaf_sync.color._types import RGBTuple

_log = logging.getLogger(__name__)


def resolve_device_zone_indices(
    source_zone_count: int,
    *,
    device_zone_count: int,
    reverse: bool = False,
    fixed_mapping: Optional[Sequence[int]] = None,
) -> List[int]:
    src_n = max(0, int(source_zone_count))
    dst_n = max(0, int(device_zone_count))
    if src_n == 0 or dst_n == 0:
        return []

    if fixed_mapping:
        result = [
            int(fixed_mapping[i]) % src_n if i < len(fixed_mapping) else 0 for i in range(dst_n)
        ]
        for i, orig in enumerate(fixed_mapping):
            if i < len(fixed_mapping) and int(orig) >= src_n:
                _log.warning(
                    "Calibration zone %d (%s) out of range [0, %d); wrapped via modulo",
                    i,
                    orig,
                    src_n,
                )
        return result

    out = [i % src_n for i in range(dst_n)]
    if reverse:
        out = [((src_n - 1) - idx) % src_n for idx in out]
    return out


def map_colors_to_device_zones(
    screen_colors: Sequence[RGBTuple],
    *,
    device_zone_count: int,
    reverse: bool = False,
    fixed_mapping: Optional[Sequence[int]] = None,
) -> List[RGBTuple]:
    src = list(screen_colors)
    if not src:
        return [(0, 0, 0)] * max(0, int(device_zone_count))
    mapping = resolve_device_zone_indices(
        len(src),
        device_zone_count=device_zone_count,
        reverse=reverse,
        fixed_mapping=fixed_mapping,
    )
    return [src[idx] for idx in mapping]
