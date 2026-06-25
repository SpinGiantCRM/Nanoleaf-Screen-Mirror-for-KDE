"""Fixed-timestep accumulator for deterministic pipeline pacing."""

from __future__ import annotations

import time


class FixedTimestepAccumulator:
    """Glenn Fiedler fixed-timestep pattern for frame pacing."""

    def __init__(self, dt: float) -> None:
        self.dt = max(1e-6, float(dt))
        self.accumulator = 0.0
        self.previous_time = time.perf_counter()

    def tick(self) -> int:
        now = time.perf_counter()
        frame_time = now - self.previous_time
        self.previous_time = now
        self.accumulator += frame_time
        steps = int(self.accumulator / self.dt)
        self.accumulator -= steps * self.dt
        return max(1, steps)
