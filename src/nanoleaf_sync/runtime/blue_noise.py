"""Spatiotemporal blue-noise dithering before 8-bit LED quantization."""

from __future__ import annotations

from functools import lru_cache

import numpy as np


@lru_cache(maxsize=1)
def _load_blue_noise() -> np.ndarray:
    rng = np.random.default_rng(42)
    size = 64
    texture = np.zeros((size, size), dtype=np.float32)
    for _ in range(size * size):
        x = int(rng.integers(0, size))
        y = int(rng.integers(0, size))
        texture[y, x] = rng.random()
    return texture


def apply_blue_noise_dither(
    colors: np.ndarray,
    *,
    frame_index: int,
    strength: float = 0.5,
) -> np.ndarray:
    noise_tex = _load_blue_noise()
    out = np.asarray(colors, dtype=np.float32)
    if out.ndim != 2 or out.shape[1] != 3:
        return out
    for zi in range(out.shape[0]):
        tx = (zi * 7 + frame_index * 13) % 64
        ty = (zi * 11 + frame_index * 17) % 64
        noise = (float(noise_tex[ty, tx]) - 0.5) * float(strength)
        out[zi] = np.clip(out[zi] + noise * 255.0, 0.0, 255.0)
    return out
