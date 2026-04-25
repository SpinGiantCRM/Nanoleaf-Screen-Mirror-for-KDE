from __future__ import annotations

import numpy as np

from nanoleaf_sync.runtime.engine import _adaptive_one_euro_blend


def _blend(
    *,
    previous: np.ndarray,
    current: np.ndarray,
    motion_preset: str,
    smoothing: float = 0.25,
    smoothing_speed: float = 2.0,
):
    return _adaptive_one_euro_blend(
        previous=previous.astype(np.float32),
        current=current.astype(np.float32),
        smoothing=smoothing,
        smoothing_speed=smoothing_speed,
        motion_preset=motion_preset,
    )


def test_noisy_grey_sequence_stays_stable() -> None:
    prev = np.full((12, 3), 128, dtype=np.float32)
    noise = np.array([[-1, 1, 0], [1, -1, 0], [0, 1, -1], [1, 0, -1]], dtype=np.float32)
    current = prev.copy()
    current[:4] += noise
    blended, diag = _blend(previous=prev, current=current, motion_preset="responsive")
    assert np.max(np.abs(blended - prev)) <= 1.0
    assert diag.deadband_active is True


def test_slow_colour_ramp_fades_smoothly() -> None:
    prev = np.full((10, 3), 40, dtype=np.float32)
    current = prev + 12.0
    blended, _diag = _blend(previous=prev, current=current, motion_preset="calm")
    assert np.all(blended > prev)
    assert np.all(blended < current)


def test_large_colour_jump_responds_quickly() -> None:
    prev = np.full((8, 3), 10, dtype=np.float32)
    current = np.full((8, 3), 240, dtype=np.float32)
    blended, _diag = _blend(previous=prev, current=current, motion_preset="responsive")
    assert float(np.mean(blended - prev)) > 100.0


def test_calm_smooths_more_than_responsive() -> None:
    prev = np.full((12, 3), 60, dtype=np.float32)
    current = prev + 20.0
    calm, _ = _blend(previous=prev, current=current, motion_preset="calm")
    responsive, _ = _blend(previous=prev, current=current, motion_preset="responsive")
    assert float(np.mean(calm - prev)) < float(np.mean(responsive - prev))


def test_dynamic_responds_faster_than_responsive() -> None:
    prev = np.full((12, 3), 60, dtype=np.float32)
    current = prev + 20.0
    responsive, _ = _blend(previous=prev, current=current, motion_preset="responsive")
    dynamic, _ = _blend(previous=prev, current=current, motion_preset="dynamic")
    assert float(np.mean(dynamic - prev)) > float(np.mean(responsive - prev))


def test_high_motion_scene_reduces_smoothing_vs_static() -> None:
    prev = np.full((16, 3), 120, dtype=np.float32)
    low_motion = prev + np.tile(np.array([[4, 4, 4]], dtype=np.float32), (16, 1))
    high_motion = prev + np.linspace(12, 90, 16, dtype=np.float32)[:, None]
    _, low_diag = _blend(previous=prev, current=low_motion, motion_preset="responsive")
    _, high_diag = _blend(previous=prev, current=high_motion, motion_preset="responsive")
    assert high_diag.max_effective_alpha > low_diag.max_effective_alpha
    assert high_diag.scene_activity in {"medium", "high"}


def test_tiny_changes_below_deadband_do_not_flicker() -> None:
    prev = np.full((6, 3), 100, dtype=np.float32)
    current = prev + np.array([0.8, -0.6, 0.4], dtype=np.float32)
    blended, diag = _blend(previous=prev, current=current, motion_preset="calm")
    assert np.max(np.abs(blended - prev)) < 0.2
    assert diag.deadband_active is True


def test_per_zone_locality_is_preserved() -> None:
    prev = np.full((10, 3), 80, dtype=np.float32)
    current = prev.copy()
    current[0] += 120.0
    blended, _diag = _blend(previous=prev, current=current, motion_preset="responsive")
    assert float(np.mean(blended[0] - prev[0])) > 40.0
    assert float(np.max(np.abs(blended[1:] - prev[1:]))) < 1.0
