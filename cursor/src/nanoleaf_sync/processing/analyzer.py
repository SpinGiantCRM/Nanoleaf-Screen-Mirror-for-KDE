from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

import numpy as np


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


def average_color(image: np.ndarray) -> Tuple[int, int, int]:
    """
    Return the average RGB color for the entire image.
    """

    img = _ensure_rgb_u8(image)
    # Compute in float for numerical stability; output int channels.
    mean = img.mean(axis=(0, 1))
    r, g, b = mean.tolist()
    return int(r), int(g), int(b)


def dominant_colors_kmeans(
    image: np.ndarray,
    n_clusters: int = 3,
    *,
    sample_pixels: int = 10_000,
    max_iter: int = 15,
    rng_seed: int = 0,
) -> List[Tuple[int, int, int]]:
    """
    Find dominant colors using k-means clustering.

    Notes:
    - This implementation is intentionally dependency-free (pure NumPy).
    - To keep latency bounded, it performs k-means over a random pixel sample.
    - Output clusters are sorted by size (largest first).
    """

    if n_clusters < 1:
        raise ValueError("n_clusters must be >= 1")

    img = _ensure_rgb_u8(image)
    h, w, _ = img.shape
    pixels = img.reshape(h * w, 3)

    # Sample pixels to limit runtime.
    total = pixels.shape[0]
    if total == 0:
        return [(0, 0, 0)]

    n = min(total, int(sample_pixels))
    rng = np.random.default_rng(rng_seed)
    idx = rng.choice(total, size=n, replace=False if n < total else True)
    sample = pixels[idx].astype(np.float32, copy=False)

    # Initialize centroids by sampling random points.
    initial_idx = rng.choice(
        sample.shape[0],
        size=n_clusters,
        replace=False if n_clusters <= sample.shape[0] else True,
    )
    centers = sample[initial_idx]  # (K, 3)

    labels = np.zeros(sample.shape[0], dtype=np.int32)

    for _ in range(max_iter):
        # Assign each point to nearest centroid (Euclidean in RGB space).
        # (N, K) distances computed without huge intermediate arrays.
        # distances = np.sum((sample[:, None, :] - centers[None, :, :]) ** 2, axis=2)  # (N, K)
        diff = sample[:, None, :] - centers[None, :, :]
        distances = np.sum(diff * diff, axis=2)
        new_labels = np.argmin(distances, axis=1)

        if np.array_equal(new_labels, labels):
            break
        labels = new_labels

        # Update centers as mean of assigned points.
        for k in range(n_clusters):
            mask = labels == k
            if not np.any(mask):
                # Empty cluster: re-seed it to a random point to keep k-means stable.
                centers[k] = sample[rng.integers(0, sample.shape[0])]
            else:
                centers[k] = sample[mask].mean(axis=0)

    # Sort clusters by the number of assigned points.
    counts = np.bincount(labels, minlength=n_clusters)
    order = np.argsort(-counts)  # descending counts

    centers_u8 = np.clip(np.rint(centers[order]), 0, 255).astype(np.uint8)
    return [tuple(map(int, c.tolist())) for c in centers_u8]


def zone_colors(
    image: np.ndarray,
    zones: Sequence[Tuple[int, int, int, int]],
) -> List[Tuple[int, int, int]]:
    """
    Given a list of screen regions and an image, return average RGB per zone.

    zones: list of (x, y, width, height) in pixel coordinates.
    """

    img = _ensure_rgb_u8(image)
    h, w, _ = img.shape

    out: List[Tuple[int, int, int]] = []
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
