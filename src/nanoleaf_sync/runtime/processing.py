from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np

from nanoleaf_sync.config.model import ZoneConfig


RGBTuple = Tuple[int, int, int]


def apply_brightness(colors: Sequence[RGBTuple], brightness: float) -> List[RGBTuple]:
    if not colors:
        return []
    b = max(0.0, min(1.0, float(brightness)))
    if b == 1.0:
        return list(colors)
    arr = np.asarray(colors, dtype=np.float32)
    out = np.clip(np.rint(arr * b), 0.0, 255.0).astype(np.uint8)
    return [tuple(int(c) for c in row) for row in out]


def ema_smooth(
    prev: Sequence[RGBTuple],
    current: Sequence[RGBTuple],
    alpha: float,
) -> List[RGBTuple]:
    """Exponential moving average: ema = alpha * current + (1-alpha) * prev."""

    a = max(0.0, min(1.0, float(alpha)))
    if not prev:
        return list(current)
    if not current:
        return []

    n = min(len(prev), len(current))
    prev_arr = np.asarray(prev[:n], dtype=np.float32)
    cur_arr = np.asarray(current[:n], dtype=np.float32)
    mixed = (a * cur_arr) + ((1.0 - a) * prev_arr)
    out = np.clip(np.rint(mixed), 0.0, 255.0).astype(np.uint8)
    return [tuple(int(c) for c in row) for row in out]


def zones_from_config(
    zones: Sequence[ZoneConfig], width: int, height: int
) -> List[Tuple[int, int, int, int]]:
    if not zones:
        return [(0, 0, width, height)]

    out: List[Tuple[int, int, int, int]] = []
    for z in zones:
        out.append((int(z.x * width), int(z.y * height), int(z.w * width), int(z.h * height)))
    return out
