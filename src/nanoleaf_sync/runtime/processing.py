from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from nanoleaf_sync.color._types import RGBTuple
from nanoleaf_sync.config.model import ZoneConfig
from nanoleaf_sync.runtime.srgb import (
    linear01_to_srgb_float,
    srgb_encoded_float_to_linear01,
)


def apply_brightness(colors: Sequence[RGBTuple], brightness: float) -> list[RGBTuple]:
    if not colors:
        return []
    b = max(0.0, min(1.0, float(brightness)))
    if b == 1.0:
        return colors if isinstance(colors, list) else list(colors)
    arr = np.asarray(colors, dtype=np.float32)
    linear = srgb_encoded_float_to_linear01(arr)
    out = linear01_to_srgb_float(linear * b)
    return [
        tuple(int(c) for c in row)
        for row in np.clip(np.rint(out), 0, 255).astype(np.uint8, copy=False)
    ]


def ema_smooth(
    prev: Sequence[RGBTuple],
    current: Sequence[RGBTuple],
    alpha: float,
) -> list[RGBTuple]:
    """Exponential moving average: ema = alpha * current + (1-alpha) * prev."""

    a = max(0.0, min(1.0, float(alpha)))
    if not prev or not current:
        return list(current) if current else []

    n = min(len(prev), len(current))
    cur_arr = np.asarray(current[:n], dtype=np.float32)
    prev_arr = np.asarray(prev[:n], dtype=np.float32)
    cur_linear = srgb_encoded_float_to_linear01(cur_arr)
    prev_linear = srgb_encoded_float_to_linear01(prev_arr)
    blended = (a * cur_linear) + ((1.0 - a) * prev_linear)
    out = linear01_to_srgb_float(blended)
    return [
        tuple(int(c) for c in row)
        for row in np.clip(np.rint(out), 0, 255).astype(np.uint8, copy=False)
    ]


def zones_from_config(
    zones: Sequence[ZoneConfig], width: int, height: int
) -> list[tuple[int, int, int, int]]:
    if not zones:
        return [(0, 0, width, height)]

    out: list[tuple[int, int, int, int]] = []
    for z in zones:
        out.append((int(z.x * width), int(z.y * height), int(z.w * width), int(z.h * height)))
    return out


def scale_zones_to_display(
    zones_px: Sequence[tuple[int, int, int, int]],
    *,
    capture_width: int,
    capture_height: int,
    display_width: int,
    display_height: int,
) -> list[tuple[int, int, int, int]]:
    cap_w = max(1, int(capture_width))
    cap_h = max(1, int(capture_height))
    disp_w = max(1, int(display_width))
    disp_h = max(1, int(display_height))
    if cap_w == disp_w and cap_h == disp_h:
        return [(int(x), int(y), int(w), int(h)) for x, y, w, h in zones_px]
    sx = disp_w / float(cap_w)
    sy = disp_h / float(cap_h)
    scaled: list[tuple[int, int, int, int]] = []
    for x, y, w, h in zones_px:
        scaled.append(
            (
                int(round(x * sx)),
                int(round(y * sy)),
                max(1, int(round(w * sx))),
                max(1, int(round(h * sy))),
            )
        )
    return scaled
