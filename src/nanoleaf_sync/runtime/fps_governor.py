"""Adaptive FPS governor that adjusts target frame rate based on pipeline latency.

Uses a sliding window of recent latencies and a tiered FPS staircase.
Motion envelope follower provides preemptive FPS reduction on scene changes.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from nanoleaf_sync.runtime.novel_features import motion_governor_enabled

FPS_TIERS = [120, 90, 60, 45, 30]

_MOTION_ATTACK_GAIN = 2.0
_MOTION_RELEASE_DECAY = 0.85
_MOTION_ENTER_THRESHOLD = 18.0
_MOTION_EXIT_THRESHOLD = 6.0
_MOTION_EXIT_FRAMES = 10
_MOTION_RAMP_FPS_PER_FRAME = 5


def governor_min_fps_floor(config_fps: int) -> int:
    fps = max(1, int(config_fps))
    return min(fps, FPS_TIERS[-1])


_UP_THRESHOLD = 0.60
_DOWN_THRESHOLD = 0.80
_WINDOW_SIZE = 30
_WARMUP_FRAMES = 10
_UP_CONSECUTIVE = 50


def _nearest_tier_at_or_below(fps: int) -> int:
    target = max(1, int(fps))
    for tier in FPS_TIERS:
        if tier <= target:
            return tier
    return FPS_TIERS[-1]


def _step_fps_down_to(target: int, current: int) -> int:
    goal = _nearest_tier_at_or_below(target)
    for tier in reversed(FPS_TIERS):
        if tier < current and tier >= goal:
            return tier
    for tier in reversed(FPS_TIERS):
        if tier < current:
            return tier
    return current


class FPSGovernor:
    """Adaptive FPS governor."""

    def __init__(self, initial_fps: int = 60, *, min_fps_floor: int = 30) -> None:
        self._config_fps = max(1, int(initial_fps))
        self._target_fps = int(initial_fps)
        self._min_fps_floor = max(1, int(min_fps_floor))
        self._latency_window: deque[float] = deque(maxlen=_WINDOW_SIZE)
        self._frame_count = 0
        self._consecutive_low = 0
        self._transitions: list[tuple[int, int, int]] = []
        self._motion_envelope = 0.0
        self._motion_exit_counter = 0
        self._motion_active = False
        self._last_motion_signal = 0.0

    def signal_motion(self, motion_value: float) -> None:
        motion = max(0.0, float(motion_value))
        self._last_motion_signal = motion
        if not motion_governor_enabled():
            return
        self._motion_envelope = max(
            motion * _MOTION_ATTACK_GAIN,
            self._motion_envelope * _MOTION_RELEASE_DECAY,
        )

    @property
    def motion_envelope(self) -> float:
        return float(self._motion_envelope)

    @property
    def last_motion_signal(self) -> float:
        return float(self._last_motion_signal)

    def record_frame(self, latency_ms: float) -> int:
        self._latency_window.append(float(latency_ms))
        self._frame_count += 1

        if motion_governor_enabled():
            self._apply_motion_enter()

        if self._frame_count <= _WARMUP_FRAMES or len(self._latency_window) < 5:
            return self._target_fps

        p95 = float(np.percentile(list(self._latency_window), 95))
        budget_ms = 1000.0 / max(1, self._target_fps)
        utilisation = p95 / budget_ms if budget_ms > 0 else 0.0

        if utilisation > _DOWN_THRESHOLD:
            self._consecutive_low = 0
            self._motion_exit_counter = 0
            self._motion_active = True
            current = self._tier_index()
            floor_index = self._floor_tier_index()
            if current < floor_index:
                old = self._target_fps
                self._target_fps = FPS_TIERS[current + 1]
                self._transitions.append((self._frame_count, old, self._target_fps))
                self._latency_window.clear()
        elif utilisation < _UP_THRESHOLD:
            if motion_governor_enabled():
                self._apply_motion_recovery()
            if not self._motion_active:
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

    def _apply_motion_enter(self) -> None:
        if self._motion_envelope < _MOTION_ENTER_THRESHOLD:
            return
        self._motion_active = True
        self._motion_exit_counter = 0
        motion_cap = max(
            self._min_fps_floor,
            int(self._config_fps * 0.6),
        )
        if self._target_fps > motion_cap:
            old = self._target_fps
            self._target_fps = _step_fps_down_to(motion_cap, self._target_fps)
            if self._target_fps != old:
                self._transitions.append((self._frame_count, old, self._target_fps))
                self._latency_window.clear()

    def _apply_motion_recovery(self) -> None:
        if self._motion_envelope >= _MOTION_EXIT_THRESHOLD:
            self._motion_exit_counter = 0
            return
        self._motion_exit_counter += 1
        if not self._motion_active or self._motion_exit_counter < _MOTION_EXIT_FRAMES:
            return
        goal = min(self._config_fps, self._target_fps + _MOTION_RAMP_FPS_PER_FRAME)
        for tier in FPS_TIERS:
            if tier >= goal:
                goal = tier
                break
        if goal > self._target_fps:
            old = self._target_fps
            self._target_fps = goal
            self._transitions.append((self._frame_count, old, self._target_fps))
        if self._target_fps >= self._config_fps:
            self._motion_active = False

    @property
    def target_fps(self) -> int:
        return self._target_fps

    def get_metrics(self) -> dict[str, float | int | list[tuple[int, int, int]]]:
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
            "motion_envelope": round(self._motion_envelope, 4),
            "last_motion_signal": round(self._last_motion_signal, 4),
            "transitions": self._transitions[-10:],
        }

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
