"""Shared capture utilities used across backends."""

from __future__ import annotations

import numpy as np


def _resize_to_target(
    *,
    frame: np.ndarray,
    target_height: int,
    target_width: int,
    index_cache: dict[tuple[int, int, int, int], tuple[np.ndarray, np.ndarray]] | None = None,
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

    if y_idx is None:
        y_idx = np.linspace(0, frame.shape[0] - 1, target_height).astype(np.intp)
        x_idx = np.linspace(0, frame.shape[1] - 1, target_width).astype(np.intp)
        if index_cache is not None:
            index_cache[cache_key] = (y_idx, x_idx)
            if len(index_cache) > index_cache_limit:
                index_cache.pop(next(iter(index_cache)))

    return frame[y_idx[:, None], x_idx[None, :], :]
