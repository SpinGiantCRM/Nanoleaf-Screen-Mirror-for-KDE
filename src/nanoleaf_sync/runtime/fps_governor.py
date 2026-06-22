"""Adaptive FPS governor that adjusts target frame rate based on pipeline latency.

Uses a sliding window of recent latencies and a tiered FPS staircase.
"""

from __future__ import annotations

from collections import deque

import numpy as np

FPS_TIERS = [120, 90, 60, 45, 30]


def governor_min_fps_floor(config_fps: int) -> int:
    fps = max(1, int(config_fps))
    if fps >= 60:
        return min(fps, 60)
    if fps >= 30:
        return min(fps, 30)
    return fps


_UP_THRESHOLD = 0.60  # utilisation below this for N consecutive frames → step up
_DOWN_THRESHOLD = 0.80  # utilisation above this → step down
_WINDOW_SIZE = 30
_WARMUP_FRAMES = 10
_UP_CONSECUTIVE = 50


class FPSGovernor:
    """Adaptive FPS governor.

    Tracks a sliding window of end-to-end pipeline latencies and steps the
    target FPS up or down across a fixed set of tiers when utilisation exceeds
    pre-defined thresholds.

    Parameters
    ----------
    initial_fps:
        Starting target FPS.  Clamped to a tier if it does not match one
        exactly.
    """

    def __init__(self, initial_fps: int = 60, *, min_fps_floor: int = 30) -> None:
        self._target_fps = int(initial_fps)
        self._min_fps_floor = max(1, int(min_fps_floor))
        self._latency_window: deque[float] = deque(maxlen=_WINDOW_SIZE)
        self._frame_count = 0
        self._consecutive_low = 0
        self._transitions: list[tuple[int, int, int]] = []  # (frame, old_fps, new_fps)

    # -- public API ------------------------------------------------------------

    def record_frame(self, latency_ms: float) -> int:
        """Feed a new end-to-end latency sample.

        Returns the *current* target FPS (which may have changed as a result
        of this call).
        """
        self._latency_window.append(float(latency_ms))
        self._frame_count += 1

        if self._frame_count <= _WARMUP_FRAMES or len(self._latency_window) < 5:
            return self._target_fps

        p95 = float(np.percentile(list(self._latency_window), 95))
        budget_ms = 1000.0 / max(1, self._target_fps)
        utilisation = p95 / budget_ms if budget_ms > 0 else 0.0

        if utilisation > _DOWN_THRESHOLD:
            self._consecutive_low = 0
            current = self._tier_index()
            floor_index = self._floor_tier_index()
            if current < floor_index:
                old = self._target_fps
                self._target_fps = FPS_TIERS[current + 1]
                self._transitions.append((self._frame_count, old, self._target_fps))
                self._latency_window.clear()
        elif utilisation < _UP_THRESHOLD:
            self._consecutive_low += 1
            if self._consecutive_low >= _UP_CONSECUTIVE:
                current = self._tier_index()
                if current > 0:
                    old = self._target_fps
                    self._target_fps = FPS_TIERS[current - 1]
                    self._transitions.append((self._frame_count, old, self._target_fps))
                    self._latency_window.clear()
                self._consecutive_low = 0
        else:
            self._consecutive_low = 0

        return self._target_fps

    @property
    def target_fps(self) -> int:
        """Current governor-determined target FPS."""
        return self._target_fps

    def get_metrics(self) -> dict[str, float | int | list[tuple[int, int, int]]]:
        """Return a diagnostics dictionary."""
        if len(self._latency_window) >= 5:
            p95 = float(np.percentile(list(self._latency_window), 95))
            budget_ms = 1000.0 / max(1, self._target_fps)
            utilisation = p95 / budget_ms if budget_ms > 0 else 0.0
        else:
            p95 = 0.0
            utilisation = 0.0
        return {
            "target_fps": self._target_fps,
            "p95_latency_ms": round(p95, 3),
            "utilisation": round(utilisation, 4),
            "window_size": len(self._latency_window),
            "frame_count": self._frame_count,
            "consecutive_low_frames": self._consecutive_low,
            "transitions": self._transitions[-10:],
        }

    # -- internal --------------------------------------------------------------

    def _tier_index(self) -> int:
        try:
            return FPS_TIERS.index(self._target_fps)
        except ValueError:
            for i, tier in enumerate(FPS_TIERS):
                if self._target_fps >= tier:
                    return i
            return len(FPS_TIERS) - 1

    def _floor_tier_index(self) -> int:
        for index in range(len(FPS_TIERS) - 1, -1, -1):
            if FPS_TIERS[index] >= self._min_fps_floor:
                return index
        return len(FPS_TIERS) - 1


def capture_interval_budget_ms(
    *,
    target_fps: int,
    hid_output_work_ewma_ms: float | None,
) -> float | None:
    if hid_output_work_ewma_ms is None:
        return None
    fps = max(1, int(target_fps))
    output_budget_ms = 1000.0 / float(fps)
    work = float(hid_output_work_ewma_ms)
    if work <= output_budget_ms * 0.75:
        return output_budget_ms
    return max(output_budget_ms, work * 1.05)
