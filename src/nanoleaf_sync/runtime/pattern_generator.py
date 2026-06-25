from __future__ import annotations

import math

import numpy as np


def moving_bar(
    *,
    width: int,
    height: int,
    t: float,
    bar_height: int = 40,
    speed_edge_lengths_per_sec: float = 2.0,
) -> np.ndarray:
    w = max(1, int(width))
    h = max(1, int(height))
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    bar_w = max(1, w // 3)
    travel = float(speed_edge_lengths_per_sec) * float(w) * float(t)
    x0 = int(travel) % max(1, w + bar_w) - bar_w
    y0 = 0
    y1 = min(h, max(1, int(bar_height)))
    x_start = max(0, x0)
    x_end = min(w, x0 + bar_w)
    if x_end > x_start:
        frame[y0:y1, x_start:x_end] = (255, 255, 255)
    return frame


def anchor_blip(
    *,
    width: int,
    height: int,
    center_x: int,
    center_y: int,
    radius: int = 24,
) -> np.ndarray:
    w = max(1, int(width))
    h = max(1, int(height))
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    cx = int(center_x)
    cy = int(center_y)
    r = max(4, int(radius))
    y_grid, x_grid = np.ogrid[:h, :w]
    mask = (x_grid - cx) ** 2 + (y_grid - cy) ** 2 <= r * r
    frame[mask] = (255, 255, 255)
    return frame


def rainbow_sweep(
    *,
    width: int,
    height: int,
    t: float,
    perimeter_zone_count: int,
) -> np.ndarray:
    w = max(1, int(width))
    h = max(1, int(height))
    zones = max(4, int(perimeter_zone_count))
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    phase = float(t) % 1.0
    for i in range(zones):
        hue = (float(i) / float(zones) + phase) % 1.0
        rgb = _hsv_to_rgb(hue, 1.0, 1.0)
        t0 = float(i) / float(zones)
        t1 = float(i + 1) / float(zones)
        _paint_perimeter_segment(frame, t0, t1, rgb)
    return frame


def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    i = int(h * 6.0)
    f = h * 6.0 - float(i)
    p = int(255 * v * (1.0 - s))
    q = int(255 * v * (1.0 - f * s))
    t = int(255 * v * (1.0 - (1.0 - f) * s))
    vv = int(255 * v)
    i %= 6
    if i == 0:
        return vv, t, p
    if i == 1:
        return q, vv, p
    if i == 2:
        return p, vv, t
    if i == 3:
        return p, q, vv
    if i == 4:
        return t, p, vv
    return vv, p, q


def _paint_perimeter_segment(
    frame: np.ndarray,
    t0: float,
    t1: float,
    rgb: tuple[int, int, int],
) -> None:
    h, w, _ = frame.shape
    thickness = max(2, min(h, w) // 40)
    mid = (t0 + t1) * 0.5
    if mid < 0.25:
        x0 = int(t0 * 4.0 * w)
        x1 = int(t1 * 4.0 * w)
        frame[0:thickness, x0:x1] = rgb
    elif mid < 0.5:
        y0 = int((t0 - 0.25) * 4.0 * h)
        y1 = int((t1 - 0.25) * 4.0 * h)
        frame[y0:y1, w - thickness : w] = rgb
    elif mid < 0.75:
        x0 = int((1.0 - t1) * 4.0 * w)
        x1 = int((1.0 - t0) * 4.0 * w)
        frame[h - thickness : h, x0:x1] = rgb
    else:
        y0 = int((1.0 - t1) * 4.0 * h)
        y1 = int((1.0 - t0) * 4.0 * h)
        frame[y0:y1, 0:thickness] = rgb


def corner_screen_position(
    *,
    corner: str,
    width: int,
    height: int,
    estimate_zone: int,
    zones_per_side: tuple[int, int, int, int],
) -> tuple[int, int]:
    w = max(1, int(width))
    h = max(1, int(height))
    top, right, bottom, left = (max(0, int(v)) for v in zones_per_side)
    zone = max(0, int(estimate_zone))
    if corner == "top_left":
        return 0, 0
    if corner == "top_right":
        return w - 1, 0
    if corner == "bottom_right":
        return w - 1, h - 1
    if corner == "bottom_left":
        return 0, h - 1
    total = max(1, top + right + bottom + left)
    t = float(zone) / float(total)
    angle = t * 2.0 * math.pi
    cx = int((0.5 + 0.45 * math.cos(angle - math.pi / 2.0)) * w)
    cy = int((0.5 + 0.45 * math.sin(angle - math.pi / 2.0)) * h)
    return max(0, min(w - 1, cx)), max(0, min(h - 1, cy))
