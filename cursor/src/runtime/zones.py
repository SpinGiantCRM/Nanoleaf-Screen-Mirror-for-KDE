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
) -> List[RGBTuple]:
    """
    Given a list of screen regions and an image, return average RGB per zone.

    zones: list of (x, y, width, height) in pixel coordinates.
    """

    img = _ensure_rgb_u8(image)
    h, w, _ = img.shape

    out: List[RGBTuple] = []
    for x, y, zw, zh in zones:
        # Clip zone bounds to the image.
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(w, x0 + int(zw))
        y1 = min(h, y0 + int(zh))

        if x1 <= x0 or y1 <= y0:
            out.append((0, 0, 0))
            continue

        zone = img[y0:y1, x0:x1, :]
        out.append(average_color(zone))

    return out
