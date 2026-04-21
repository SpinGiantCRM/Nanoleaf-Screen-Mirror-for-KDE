from __future__ import annotations

from typing import List, Tuple

import numpy as np

from nanoleaf_sync.runtime.zones import _ensure_rgb_u8


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
        return [(0, 0, 0)] * n_clusters

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
