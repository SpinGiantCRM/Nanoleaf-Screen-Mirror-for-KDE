from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np


RGBTuple = Tuple[int, int, int]
ZoneRect = Tuple[int, int, int, int]


def _ensure_rgb_u8(image: np.ndarray) -> np.ndarray:
    """
    Ensure `image` is an RGB uint8 array.

    The rest of this module assumes:
    - shape: (H, W, 3)
    - dtype: uint8
    """

    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"Expected image shape (H, W, 3), got {image.shape}")
    if image.dtype != np.uint8:
        # Use a copy since the dtype conversion changes values.
        return image.astype(np.uint8, copy=False)
    return image


def average_color(image: np.ndarray) -> RGBTuple:
    """
    Return the average RGB color for the entire image.
    """

    img = _ensure_rgb_u8(image)
    # Compute in float for numerical stability; output int channels.
    mean = img.mean(axis=(0, 1))
    r, g, b = mean.tolist()
    return int(r), int(g), int(b)


def zone_colors(
    image: np.ndarray,
    zones: Sequence[ZoneRect],
    *,
    sample_step: int = 1,
) -> List[RGBTuple]:
    zone_arr = zone_colors_array(image, zones, sample_step=sample_step)
    return [tuple(int(c) for c in row) for row in zone_arr]


def zone_colors_array(
    image: np.ndarray,
    zones: Sequence[ZoneRect],
    *,
    sample_step: int = 1,
) -> np.ndarray:
    """
    Given a list of screen regions and an image, return average RGB per zone.

    zones: list of (x, y, width, height) in pixel coordinates.
    """

    img = _ensure_rgb_u8(image)
    h, w, _ = img.shape

    if not zones:
        return np.zeros((0, 3), dtype=np.uint8)

    step = max(1, int(sample_step))

    zones_arr = np.asarray(zones, dtype=np.intp)
    x = zones_arr[:, 0]
    y = zones_arr[:, 1]
    zw = zones_arr[:, 2]
    zh = zones_arr[:, 3]

    if step > 1:
        # Sample a strided working image and map zone coordinates into that space.
        img = img[::step, ::step, :]
        h, w, _ = img.shape
        x = x // step
        y = y // step
        # Ceil-div to preserve minimally-sized zones after downsampling.
        zw = (zw + (step - 1)) // step
        zh = (zh + (step - 1)) // step

    x0 = np.clip(x, 0, w)
    y0 = np.clip(y, 0, h)
    x1 = np.clip(x0 + zw, 0, w)
    y1 = np.clip(y0 + zh, 0, h)

    areas = (x1 - x0) * (y1 - y0)

    # Build per-channel integral image to compute zone sums in O(1) each.
    integral = np.zeros((h + 1, w + 1, 3), dtype=np.uint64)
    integral[1:, 1:, :] = img.cumsum(axis=0, dtype=np.uint64).cumsum(axis=1, dtype=np.uint64)

    sums = (
        integral[y1, x1]
        - integral[y0, x1]
        - integral[y1, x0]
        + integral[y0, x0]
    )

    means = np.zeros((len(zones), 3), dtype=np.uint8)
    valid = areas > 0
    if valid.any():
        means[valid] = (sums[valid] // areas[valid, None]).astype(np.uint8, copy=False)

    return means
