from __future__ import annotations

from typing import List, Sequence, Tuple

from config import ZoneConfig


RGBTuple = Tuple[int, int, int]


def _clamp_u8(x: float) -> int:
    if x <= 0:
        return 0
    if x >= 255:
        return 255
    return int(round(x))


def apply_brightness(colors: Sequence[RGBTuple], brightness: float) -> List[RGBTuple]:
    b = max(0.0, min(1.0, float(brightness)))
    if b == 1.0:
        return list(colors)
    out: List[RGBTuple] = []
    for r, g, bb in colors:
        out.append((_clamp_u8(r * b), _clamp_u8(g * b), _clamp_u8(bb * b)))
    return out


def ema_smooth(
    prev: Sequence[RGBTuple],
    current: Sequence[RGBTuple],
    alpha: float,
) -> List[RGBTuple]:
    """Exponential moving average: ema = alpha * current + (1-alpha) * prev."""

    a = max(0.0, min(1.0, float(alpha)))
    if not prev:
        return list(current)

    out: List[RGBTuple] = []
    for (pr, pg, pb), (cr, cg, cb) in zip(prev, current):
        out.append(
            (
                _clamp_u8(a * cr + (1.0 - a) * pr),
                _clamp_u8(a * cg + (1.0 - a) * pg),
                _clamp_u8(a * cb + (1.0 - a) * pb),
            )
        )
    return out


def zones_from_config(
    zones: Sequence[ZoneConfig], width: int, height: int
) -> List[Tuple[int, int, int, int]]:
    if not zones:
        return [(0, 0, width, height)]

    out: List[Tuple[int, int, int, int]] = []
    for z in zones:
        out.append((int(z.x * width), int(z.y * height), int(z.w * width), int(z.h * height)))
    return out
