from __future__ import annotations

from nanoleaf_sync.config.presets import SAMPLING_MODE_AREA_AVERAGE, SAMPLING_MODE_EDGE_DIRECT
from nanoleaf_sync.runtime.color_pipeline import _resolve_live_sampling_mode


def test_edge_direct_falls_back_to_area_average_during_motion() -> None:
    mode, active, dwell = _resolve_live_sampling_mode(
        resolved_sampling_mode=SAMPLING_MODE_EDGE_DIRECT,
        prior_zone_sample_motion=14.0,
    )
    assert mode == SAMPLING_MODE_AREA_AVERAGE
    assert active is True
    assert dwell == 3


def test_edge_direct_kept_when_scene_is_static() -> None:
    mode, active, dwell = _resolve_live_sampling_mode(
        resolved_sampling_mode=SAMPLING_MODE_EDGE_DIRECT,
        prior_zone_sample_motion=2.0,
    )
    assert mode == SAMPLING_MODE_EDGE_DIRECT
    assert active is False
    assert dwell == 0


def test_area_average_hysteresis_exits_below_exit_threshold() -> None:
    mode, active, dwell = _resolve_live_sampling_mode(
        resolved_sampling_mode=SAMPLING_MODE_EDGE_DIRECT,
        prior_zone_sample_motion=6.0,
        prior_area_average_mode=True,
    )
    assert mode == SAMPLING_MODE_EDGE_DIRECT
    assert active is False
    assert dwell == 3


def test_area_average_hysteresis_stays_above_exit_threshold() -> None:
    mode, active, dwell = _resolve_live_sampling_mode(
        resolved_sampling_mode=SAMPLING_MODE_EDGE_DIRECT,
        prior_zone_sample_motion=8.0,
        prior_area_average_mode=True,
    )
    assert mode == SAMPLING_MODE_AREA_AVERAGE
    assert active is True
    assert dwell == 0


def test_dark_aware_sampling_falls_back_for_vivid_weighted_in_dark_scenes() -> None:
    from nanoleaf_sync.config.presets import SAMPLING_MODE_VIVID_WEIGHTED
    from nanoleaf_sync.runtime.color_pipeline import _resolve_robust_sampling_mode

    mode, active, dwell = _resolve_robust_sampling_mode(
        resolved_sampling_mode=SAMPLING_MODE_VIVID_WEIGHTED,
        prior_zone_sample_motion=2.0,
        prior_area_average_mode=False,
        prev_sampled_zone_colors=[(8, 8, 8)] * 8,
        letterbox_active=False,
    )
    assert mode == SAMPLING_MODE_AREA_AVERAGE
    assert active is True
    assert dwell == 0


def test_dark_aware_sampling_falls_back_when_letterbox_active() -> None:
    from nanoleaf_sync.config.presets import SAMPLING_MODE_VIVID_WEIGHTED
    from nanoleaf_sync.runtime.color_pipeline import _resolve_robust_sampling_mode

    mode, active, dwell = _resolve_robust_sampling_mode(
        resolved_sampling_mode=SAMPLING_MODE_VIVID_WEIGHTED,
        prior_zone_sample_motion=2.0,
        prior_area_average_mode=False,
        prev_sampled_zone_colors=[],
        letterbox_active=True,
    )
    assert mode == SAMPLING_MODE_AREA_AVERAGE
    assert active is True
    assert dwell == 0
