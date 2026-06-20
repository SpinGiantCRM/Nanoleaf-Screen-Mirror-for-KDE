from __future__ import annotations

import numpy as np

from nanoleaf_sync.runtime.predictive_sync import PredictiveSyncParams, apply_predictive_sync


def _params(**overrides: object) -> PredictiveSyncParams:
    base = dict(
        enabled=True,
        strength=0.6,
        effective_target_fps=60.0,
        config_fps=120.0,
        governor_target_fps=60.0,
        staleness_ms=20.0,
    )
    base.update(overrides)
    return PredictiveSyncParams(**base)


def test_prediction_inactive_when_staleness_within_budget() -> None:
    current = np.full((4, 3), 100.0, dtype=np.float32)
    previous = np.full((4, 3), 90.0, dtype=np.float32)
    result = apply_predictive_sync(
        smoothed=current,
        previous=previous,
        params=_params(
            governor_target_fps=90.0,
            config_fps=120.0,
            staleness_ms=10.0,
        ),
    )
    assert not result.active
    np.testing.assert_array_equal(result.colors, current)


def test_prediction_inactive_when_output_healthy_and_frame_is_only_mildly_stale() -> None:
    current = np.full((4, 3), 100.0, dtype=np.float32)
    previous = np.full((4, 3), 90.0, dtype=np.float32)
    result = apply_predictive_sync(
        smoothed=current,
        previous=previous,
        params=_params(staleness_ms=14.0, output_healthy=True),
    )
    assert not result.active
    np.testing.assert_array_equal(result.colors, current)


def test_prediction_uses_governor_cadence_not_configured_fps() -> None:
    current = np.full((4, 3), 120.0, dtype=np.float32)
    previous = np.full((4, 3), 100.0, dtype=np.float32)
    result = apply_predictive_sync(
        smoothed=current,
        previous=previous,
        params=_params(
            config_fps=120.0,
            effective_target_fps=60.0,
            governor_target_fps=60.0,
            staleness_ms=20.0,
            strength=0.8,
        ),
        median_zone_delta=20.0,
        max_zone_delta=20.0,
    )
    assert not result.active
    np.testing.assert_array_equal(result.colors, current)


def test_prediction_reports_lookahead_in_active_output_frames() -> None:
    current = np.full((4, 3), 120.0, dtype=np.float32)
    previous = np.full((4, 3), 100.0, dtype=np.float32)
    result = apply_predictive_sync(
        smoothed=current,
        previous=previous,
        params=_params(
            config_fps=120.0,
            effective_target_fps=60.0,
            governor_target_fps=60.0,
            staleness_ms=34.0,
            strength=0.8,
        ),
        median_zone_delta=20.0,
        max_zone_delta=20.0,
    )
    assert result.active
    assert 1.0 < result.lookahead_frames < 1.1


def test_prediction_runs_when_output_healthy_but_frame_is_stale() -> None:
    current = np.full((4, 3), 120.0, dtype=np.float32)
    previous = np.full((4, 3), 100.0, dtype=np.float32)
    result = apply_predictive_sync(
        smoothed=current,
        previous=previous,
        params=_params(staleness_ms=34.0, output_healthy=True, strength=0.8),
        median_zone_delta=20.0,
        max_zone_delta=20.0,
    )
    assert result.active
    assert float(np.max(result.colors)) <= 120.0
    assert float(np.min(result.colors)) >= 100.0


def test_prediction_inactive_when_staleness_too_high() -> None:
    previous = np.full((2, 3), 100.0, dtype=np.float32)
    current = np.full((2, 3), 120.0, dtype=np.float32)
    result = apply_predictive_sync(
        smoothed=current,
        previous=previous,
        params=_params(staleness_ms=50.0, strength=1.0),
    )
    assert not result.active
    np.testing.assert_array_equal(result.colors, current)


def test_staleness_polish_moves_toward_current_without_overshoot() -> None:
    previous = np.full((2, 3), 100.0, dtype=np.float32)
    current = np.full((2, 3), 120.0, dtype=np.float32)
    result = apply_predictive_sync(
        smoothed=current,
        previous=previous,
        params=_params(staleness_ms=24.0, strength=0.8, config_fps=120.0),
    )
    assert result.active
    assert float(np.max(result.colors)) <= 120.0
    assert float(np.min(result.colors)) >= 100.0
    per_zone_delta = np.max(np.abs(result.colors - current), axis=1)
    observed_step = np.max(np.abs(current - previous), axis=1)
    assert float(np.max(per_zone_delta)) <= float(np.max(observed_step)) * 0.36 + 1.0


def test_scene_cut_suppresses_prediction() -> None:
    previous = np.full((2, 3), 10.0, dtype=np.float32)
    current = np.full((2, 3), 200.0, dtype=np.float32)
    result = apply_predictive_sync(
        smoothed=current,
        previous=previous,
        params=_params(staleness_ms=24.0),
        max_zone_delta=50.0,
    )
    assert result.scene_cut_suppressed
    assert not result.active
    np.testing.assert_array_equal(result.colors, current)


def test_static_scene_without_previous_is_unchanged() -> None:
    current = np.full((2, 3), 128.0, dtype=np.float32)
    result = apply_predictive_sync(
        smoothed=current,
        previous=None,
        params=_params(staleness_ms=40.0),
    )
    assert not result.active
    np.testing.assert_array_equal(result.colors, current)


def test_static_scene_skips_prediction() -> None:
    previous = np.full((2, 3), 128.0, dtype=np.float32)
    current = np.full((2, 3), 129.0, dtype=np.float32)
    result = apply_predictive_sync(
        smoothed=current,
        previous=previous,
        params=_params(staleness_ms=24.0, strength=1.0),
        median_zone_delta=1.0,
    )
    assert not result.active
    np.testing.assert_array_equal(result.colors, current)


def test_median_dark_zones_skip_prediction() -> None:
    previous = np.full((4, 3), 8.0, dtype=np.float32)
    current = np.array(
        [[8.0, 8.0, 8.0], [9.0, 8.0, 8.0], [200.0, 200.0, 200.0], [8.0, 9.0, 8.0]],
        dtype=np.float32,
    )
    result = apply_predictive_sync(
        smoothed=current,
        previous=previous,
        params=_params(staleness_ms=24.0, strength=1.0),
    )
    assert not result.active
    np.testing.assert_array_equal(result.colors, current)


def test_low_light_neutral_scene_skips_prediction() -> None:
    previous = np.full((4, 3), 28.0, dtype=np.float32)
    current = np.array(
        [[32.0, 31.0, 33.0], [30.0, 32.0, 31.0], [34.0, 33.0, 32.0], [31.0, 30.0, 32.0]],
        dtype=np.float32,
    )
    result = apply_predictive_sync(
        smoothed=current,
        previous=previous,
        params=_params(staleness_ms=24.0, strength=1.0),
        median_zone_delta=4.0,
        max_zone_delta=6.0,
    )
    assert not result.active
    np.testing.assert_array_equal(result.colors, current)


def test_near_black_scene_skips_prediction() -> None:
    previous = np.full((2, 3), 4.0, dtype=np.float32)
    current = np.full((2, 3), 2.0, dtype=np.float32)
    result = apply_predictive_sync(
        smoothed=current,
        previous=previous,
        params=_params(staleness_ms=24.0, strength=1.0),
    )
    assert not result.active
    np.testing.assert_array_equal(result.colors, current)


def test_per_zone_dark_guard_leaves_dark_zones_unchanged() -> None:
    previous = np.array(
        [
            [100.0, 100.0, 100.0],
            [100.0, 100.0, 100.0],
            [100.0, 100.0, 100.0],
            [8.0, 8.0, 8.0],
        ],
        dtype=np.float32,
    )
    current = np.array(
        [
            [120.0, 120.0, 120.0],
            [115.0, 115.0, 115.0],
            [118.0, 118.0, 118.0],
            [4.0, 4.0, 4.0],
        ],
        dtype=np.float32,
    )
    result = apply_predictive_sync(
        smoothed=current,
        previous=previous,
        params=_params(staleness_ms=24.0, strength=0.8),
        max_zone_delta=15.0,
        median_zone_delta=8.0,
    )
    assert result.active
    np.testing.assert_array_equal(result.colors[3], current[3])
