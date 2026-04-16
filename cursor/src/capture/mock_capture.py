from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class MockCaptureParams:
    width: int
    height: int
    fps_hint: int = 30
    # Synthetic scene motion. Kept simple so it doesn't allocate too much.
    motion: float = 1.0


class MockScreenCapture:
    """
    Synthetic capture backend for development/demo.

    Why it exists:
    - Your DRM/KWin capture backends are intentionally placeholders right now.
    - A mock capture lets you validate the full pipeline:
      capture -> color -> zone mapping/calibration -> (mock) USB sending
      without depending on GPU buffer access being implemented yet.

    Output contract:
    - `capture()` returns uint8 RGB array shaped (H, W, 3)
    """

    name = "mock"

    def __init__(
        self, width: int, height: int, *, fps_hint: int = 30, motion: float = 1.0
    ) -> None:
        self.params = MockCaptureParams(
            width=width, height=height, fps_hint=fps_hint, motion=motion
        )
        self._t0 = time.perf_counter()

        # Reusable buffer to reduce allocations.
        self._frame = np.zeros((height, width, 3), dtype=np.uint8)

    def capture(self) -> np.ndarray:
        # Time parameter in seconds.
        t = (time.perf_counter() - self._t0) * float(self.params.motion)

        # Normalize x/y to [0,1] (precompute each call keeps it simple; optimize later).
        h, w = self.params.height, self.params.width
        yy = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
        xx = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :]

        # Simple animated gradient in RGB:
        # - red varies with x and time
        # - green varies with y and time
        # - blue varies with x+y and time
        r = 0.5 + 0.5 * np.sin(2.0 * np.pi * (xx + 0.1 * t))
        g = 0.5 + 0.5 * np.sin(2.0 * np.pi * (yy + 0.07 * t))
        b = 0.5 + 0.5 * np.sin(2.0 * np.pi * (xx + yy + 0.05 * t))

        # Write into reusable buffer.
        self._frame[:, :, 0] = np.clip(np.rint(r * 255.0), 0, 255).astype(np.uint8)
        self._frame[:, :, 1] = np.clip(np.rint(g * 255.0), 0, 255).astype(np.uint8)
        self._frame[:, :, 2] = np.clip(np.rint(b * 255.0), 0, 255).astype(np.uint8)
        return self._frame
