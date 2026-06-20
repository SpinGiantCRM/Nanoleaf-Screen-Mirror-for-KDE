from __future__ import annotations

import numpy as np

from nanoleaf_sync.runtime.state import ZoneRect

_CONTENT_LUMA_THRESHOLD = 4.0
_MARGIN_SCAN_STEP = 8


def _row_luma(row: np.ndarray) -> float:
    return float(
        np.mean(
            (0.2126 * row[:, 0].astype(np.float32))
            + (0.7152 * row[:, 1].astype(np.float32))
            + (0.0722 * row[:, 2].astype(np.float32))
        )
    )


def _col_luma(col: np.ndarray) -> float:
    return float(
        np.mean(
            (0.2126 * col[:, 0].astype(np.float32))
            + (0.7152 * col[:, 1].astype(np.float32))
            + (0.0722 * col[:, 2].astype(np.float32))
        )
    )


def detect_content_bounds(
    frame: np.ndarray,
    *,
    threshold: float = _CONTENT_LUMA_THRESHOLD,
    margin_scan_step: int = _MARGIN_SCAN_STEP,
) -> tuple[int, int, int, int]:
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(f"Expected frame shape (H, W, 3), got {getattr(frame, 'shape', None)}")

    h, w, _ = frame.shape
    if h <= 0 or w <= 0:
        return 0, 0, w, h

    step = max(1, int(margin_scan_step))
    y_top = 0
    for y in range(0, h, step):
        if _row_luma(frame[y, :, :]) > threshold:
            y_top = y
            break

    y_bottom = h
    for y in range(h - 1, y_top, -step):
        if _row_luma(frame[y, :, :]) > threshold:
            y_bottom = y + 1
            break

    x_left = 0
    for x in range(0, w, step):
        if _col_luma(frame[y_top:y_bottom, x, :]) > threshold:
            x_left = x
            break

    x_right = w
    for x in range(w - 1, x_left, -step):
        if _col_luma(frame[y_top:y_bottom, x, :]) > threshold:
            x_right = x + 1
            break

    if x_right <= x_left or y_bottom <= y_top:
        return 0, 0, w, h
    return x_left, y_top, x_right, y_bottom


def letterbox_margins_significant(
    frame: np.ndarray,
    bounds: tuple[int, int, int, int],
    *,
    min_margin_ratio: float = 0.08,
) -> bool:
    h, w, _ = frame.shape
    if h <= 0 or w <= 0:
        return False
    bx0, by0, bx1, by1 = bounds
    top = by0 / float(h)
    bottom = (h - by1) / float(h)
    left = bx0 / float(w)
    right = (w - bx1) / float(w)
    content_ratio = ((bx1 - bx0) * (by1 - by0)) / float(h * w)
    horizontal_letterbox = top >= min_margin_ratio and bottom >= min_margin_ratio
    vertical_letterbox = left >= min_margin_ratio and right >= min_margin_ratio
    return (horizontal_letterbox or vertical_letterbox) and content_ratio < 0.85


def _remap_zone_to_content_edge(
    x: int,
    y: int,
    zw: int,
    zh: int,
    *,
    bx0: int,
    by0: int,
    bx1: int,
    by1: int,
) -> ZoneRect:
    if y + zh <= by0:
        ny = by0
        nh = max(1, min(zh, by1 - by0))
        return x, ny, max(1, zw), nh
    if y >= by1:
        ny = max(by0, by1 - max(1, zh))
        nh = max(1, min(zh, by1 - by0))
        return x, ny, max(1, zw), nh
    if x + zw <= bx0:
        nx = bx0
        nw = max(1, min(zw, bx1 - bx0))
        return nx, y, nw, max(1, zh)
    if x >= bx1:
        nx = max(bx0, bx1 - max(1, zw))
        nw = max(1, min(zw, bx1 - bx0))
        return nx, y, nw, max(1, zh)
    return x, y, max(1, zw), max(1, zh)


def clip_zones_to_content_bounds(
    zones_px: list[ZoneRect],
    *,
    bounds: tuple[int, int, int, int],
    frame_width: int,
    frame_height: int,
) -> list[ZoneRect]:
    bx0, by0, bx1, by1 = bounds
    fw = max(1, int(frame_width))
    fh = max(1, int(frame_height))
    bx0 = max(0, min(fw, int(bx0)))
    by0 = max(0, min(fh, int(by0)))
    bx1 = max(bx0 + 1, min(fw, int(bx1)))
    by1 = max(by0 + 1, min(fh, int(by1)))

    clipped: list[ZoneRect] = []
    for x, y, zw, zh in zones_px:
        x0 = max(x, bx0)
        y0 = max(y, by0)
        x1 = min(x + zw, bx1)
        y1 = min(y + zh, by1)
        cw = max(0, x1 - x0)
        ch = max(0, y1 - y0)
        if cw <= 0 or ch <= 0:
            clipped.append(
                _remap_zone_to_content_edge(
                    x,
                    y,
                    zw,
                    zh,
                    bx0=bx0,
                    by0=by0,
                    bx1=bx1,
                    by1=by1,
                )
            )
        else:
            clipped.append((x0, y0, cw, ch))
    return clipped
