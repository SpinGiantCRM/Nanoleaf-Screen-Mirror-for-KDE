"""Shared capture utilities used across backends."""

from __future__ import annotations

from collections import OrderedDict

import numpy as np


def effective_runtime_zone_count(*, configured: int, detected: int | None) -> int | None:
    """Return the effective runtime zone count preferring the configured value."""
    configured_count = int(configured or 0)
    if configured_count > 0:
        return configured_count
    detected_count = int(detected or 0)
    if detected_count > 0:
        return detected_count
    return None


def _resize_to_target(
    *,
    frame: np.ndarray,
    target_height: int,
    target_width: int,
    index_cache: OrderedDict[tuple[int, int, int, int], tuple[np.ndarray, np.ndarray]]
    | dict[tuple[int, int, int, int], tuple[np.ndarray, np.ndarray]]
    | None = None,
    index_cache_limit: int = 8,
) -> np.ndarray:
    """Resize frame to target capture dimensions via nearest-neighbour index mapping.

    When ``index_cache`` is provided, precomputed index arrays are cached and
    reused across frames of the same source / target shape.
    """
    if frame.shape[0] == target_height and frame.shape[1] == target_width:
        return frame

    cache_key = (
        int(frame.shape[0]),
        int(frame.shape[1]),
        int(target_height),
        int(target_width),
    )

    y_idx: np.ndarray | None = None
    x_idx: np.ndarray | None = None

    if index_cache is not None:
        cached = index_cache.get(cache_key)
        if cached is not None:
            y_idx, x_idx = cached
            if isinstance(index_cache, OrderedDict):
                index_cache.move_to_end(cache_key)

    if y_idx is None:
        y_idx = np.linspace(0, frame.shape[0] - 1, target_height).astype(np.intp)
        x_idx = np.linspace(0, frame.shape[1] - 1, target_width).astype(np.intp)
        if index_cache is not None:
            index_cache[cache_key] = (y_idx, x_idx)
            if isinstance(index_cache, OrderedDict):
                index_cache.move_to_end(cache_key)
            if len(index_cache) > index_cache_limit:
                if isinstance(index_cache, OrderedDict):
                    index_cache.popitem(last=False)
                else:
                    index_cache.pop(next(iter(index_cache)))

    assert y_idx is not None and x_idx is not None  # nosec B101
    ys = np.asarray(y_idx, dtype=np.intp)
    xs = np.asarray(x_idx, dtype=np.intp)
    return frame[ys[:, None], xs[None, :], :]


def zone_box_average(
    frame: np.ndarray,
    zone: tuple[int, int, int, int],
    *,
    max_pixels: int = 256,
) -> np.ndarray:
    """Area-weighted zone colour using strided box-filter anti-aliasing."""
    x, y, w, h = (int(zone[0]), int(zone[1]), int(zone[2]), int(zone[3]))
    if w <= 0 or h <= 0:
        return np.zeros(3, dtype=np.uint8)

    frame_h, frame_w = frame.shape[:2]
    x = max(0, min(x, frame_w))
    y = max(0, min(y, frame_h))
    w = max(0, min(w, frame_w - x))
    h = max(0, min(h, frame_h - y))
    if w <= 0 or h <= 0:
        return np.zeros(3, dtype=np.uint8)

    from nanoleaf_sync.runtime.srgb import linear01_to_srgb_u8, srgb_u8_to_linear01

    patch = frame[y : y + h, x : x + w, :3]
    pixel_count = h * w
    if pixel_count <= max_pixels:
        linear_mean = srgb_u8_to_linear01(patch).reshape(-1, 3).mean(axis=0)
        return linear01_to_srgb_u8(linear_mean)

    step = max(1, int(np.sqrt(pixel_count / max_pixels)))
    h_aligned = (h // step) * step
    w_aligned = (w // step) * step
    if h_aligned <= 0 or w_aligned <= 0:
        linear_mean = srgb_u8_to_linear01(patch).reshape(-1, 3).mean(axis=0)
        return linear01_to_srgb_u8(linear_mean)

    linear_patch = srgb_u8_to_linear01(patch[:h_aligned, :w_aligned])
    blocks = linear_patch.reshape(h_aligned // step, step, w_aligned // step, step, 3)
    sampled = blocks.mean(axis=(1, 3))
    return linear01_to_srgb_u8(sampled.reshape(-1, 3).mean(axis=0))
