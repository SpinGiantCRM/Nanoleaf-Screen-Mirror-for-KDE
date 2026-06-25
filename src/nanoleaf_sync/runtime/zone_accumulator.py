"""Temporal zone-colour accumulation before output smoothing."""

from __future__ import annotations

import numpy as np


class ZoneAccumulator:
    """Exponentially-weighted temporal accumulation of zone samples."""

    def __init__(
        self,
        zone_count: int,
        *,
        alpha_min: float = 0.05,
        alpha_max: float = 0.50,
    ) -> None:
        self._accum = np.zeros((max(0, int(zone_count)), 3), dtype=np.float64)
        self._initialized = False
        self._alpha_min = float(alpha_min)
        self._alpha_max = float(alpha_max)

    def update(self, colors: np.ndarray, frame_delta: float) -> np.ndarray:
        """Accumulate zone colours with adaptive rate based on frame motion."""
        new = np.asarray(colors, dtype=np.float64)
        if new.ndim != 2 or new.shape[1] != 3:
            raise ValueError(f"Expected colors shape (N, 3), got {new.shape}")
        if self._accum.shape[0] != new.shape[0]:
            self._accum = np.zeros((new.shape[0], 3), dtype=np.float64)
            self._initialized = False

        if not self._initialized:
            self._accum = new.copy()
            self._initialized = True
            return np.clip(np.rint(self._accum), 0, 255).astype(np.uint8)

        alpha = self._alpha_min + (self._alpha_max - self._alpha_min) * np.clip(
            float(frame_delta), 0.0, 1.0
        )
        self._accum = (1.0 - alpha) * self._accum + alpha * new
        return np.clip(np.rint(self._accum), 0, 255).astype(np.uint8)

    def reset(self) -> None:
        self._accum.fill(0.0)
        self._initialized = False
