from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MockCaptureParams:
    width: int
    height: int
    fps_hint: int = 30
    motion: float = 1.0


class MockScreenCapture:
    """Synthetic capture backend for development and testing."""

    name = "mock"

    def __init__(
        self, width: int, height: int, *, fps_hint: int = 30, motion: float = 1.0
    ) -> None:
        self.last_capture_path: str | None = None
        self.params = MockCaptureParams(
            width=width, height=height, fps_hint=fps_hint, motion=motion
        )
        self._t0 = time.perf_counter()

        # Reusable output frame and coordinate grids to minimize per-frame allocations.
        self._frame = np.zeros((height, width, 3), dtype=np.uint8)
        self._yy = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
        self._xx = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]

    def capture(self) -> np.ndarray:
        t = (time.perf_counter() - self._t0) * float(self.params.motion)

        r = 0.5 + 0.5 * np.sin(2.0 * np.pi * (self._xx + 0.1 * t))
        g = 0.5 + 0.5 * np.sin(2.0 * np.pi * (self._yy + 0.07 * t))
        b = 0.5 + 0.5 * np.sin(2.0 * np.pi * (self._xx + self._yy + 0.05 * t))

        self._frame[:, :, 0] = np.clip(np.rint(r * 255.0), 0, 255).astype(np.uint8)
        self._frame[:, :, 1] = np.clip(np.rint(g * 255.0), 0, 255).astype(np.uint8)
        self._frame[:, :, 2] = np.clip(np.rint(b * 255.0), 0, 255).astype(np.uint8)
        return self._frame.copy()
