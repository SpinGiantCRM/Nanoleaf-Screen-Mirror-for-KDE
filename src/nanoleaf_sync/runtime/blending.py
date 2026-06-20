from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class AdaptiveSmoothingDiagnostics:
    scene_activity: str
    median_zone_delta: float
    max_zone_delta: float
    min_effective_alpha: float
    max_effective_alpha: float
    deadband_active: bool


def apply_neighbor_blend(mapped: np.ndarray, *, spread_mode: str) -> np.ndarray:
    mode = str(spread_mode or "balanced").strip().lower()
    weight = {"off": 0.0, "precise": 0.04, "balanced": 0.12, "soft": 0.24}.get(mode, 0.12)
    if mapped.shape[0] < 8 or weight <= 0.0:
        return mapped
    prev = np.roll(mapped, 1, axis=0)
    nxt = np.roll(mapped, -1, axis=0)
    return ((1.0 - (2.0 * weight)) * mapped) + (weight * prev) + (weight * nxt)


def adaptive_one_euro_blend(
    *,
    current: np.ndarray,
    previous: np.ndarray,
    smoothing: float,
    smoothing_speed: float = 0.75,
    motion_preset: str = "responsive",
) -> tuple[np.ndarray, AdaptiveSmoothingDiagnostics]:
    preset = str(motion_preset or "responsive").strip().lower()
    min_alpha = max(0.0, min(1.0, float(smoothing)))
    speed_gain = np.clip(float(smoothing_speed) / 4.0, 0.0, 1.0) ** 2

    delta = current - previous
    zone_delta = np.mean(np.abs(delta), axis=1)
    if zone_delta.size == 0:
        diagnostics = AdaptiveSmoothingDiagnostics(
            scene_activity="static",
            median_zone_delta=0.0,
            max_zone_delta=0.0,
            min_effective_alpha=min_alpha,
            max_effective_alpha=min_alpha,
            deadband_active=False,
        )
        return current, diagnostics

    deadband = 2.0
    tiny_blend = 0.08
    zone_gamma = 1.10
    scene_boost = {
        "static": 0.0,
        "low": 0.22,
        "medium": 0.44,
        "high": 0.70,
    }
    large_jump = 42.0
    jump_alpha_min = 0.72
    if preset == "calm":
        deadband = 3.0
        tiny_blend = 0.03
        zone_gamma = 1.35
        scene_boost = {"static": 0.0, "low": 0.16, "medium": 0.34, "high": 0.56}
        large_jump = 50.0
        jump_alpha_min = 0.58
    elif preset == "dynamic":
        deadband = 1.2
        tiny_blend = 0.14
        zone_gamma = 0.90
        scene_boost = {"static": 0.04, "low": 0.30, "medium": 0.55, "high": 0.84}
        large_jump = 34.0
        jump_alpha_min = 0.84

    median_delta = float(np.median(zone_delta))
    mean_delta = float(np.mean(zone_delta))
    max_delta = float(np.max(zone_delta))

    if median_delta < deadband * 1.15 and mean_delta < deadband * 1.4:
        scene_activity = "static"
    elif median_delta < 9.0:
        scene_activity = "low"
    elif median_delta < 24.0:
        scene_activity = "medium"
    else:
        scene_activity = "high"

    zone_motion = np.clip((zone_delta - deadband) / max(1e-6, 64.0 - deadband), 0.0, 1.0)
    zone_motion = np.power(zone_motion, zone_gamma)
    scene_motion = scene_boost[scene_activity]
    adaptive_motion = np.maximum(zone_motion, scene_motion)
    adaptive_motion *= speed_gain
    alpha_zone = min_alpha + (1.0 - min_alpha) * adaptive_motion

    large_change_mask = zone_delta >= large_jump
    if large_change_mask.any():
        fast_floor = jump_alpha_min * (0.65 + 0.35 * speed_gain)
        alpha_zone = np.where(large_change_mask, np.maximum(alpha_zone, fast_floor), alpha_zone)

    tiny_mask = zone_delta < deadband
    if tiny_mask.any():
        alpha_zone = np.where(tiny_mask, np.minimum(alpha_zone, tiny_blend), alpha_zone)

    alpha_rgb = alpha_zone[:, None]
    blended = alpha_rgb * current + (1.0 - alpha_rgb) * previous
    diagnostics = AdaptiveSmoothingDiagnostics(
        scene_activity=scene_activity,
        median_zone_delta=median_delta,
        max_zone_delta=max_delta,
        min_effective_alpha=float(np.min(alpha_zone)),
        max_effective_alpha=float(np.max(alpha_zone)),
        deadband_active=bool(tiny_mask.any()),
    )
    return blended, diagnostics
