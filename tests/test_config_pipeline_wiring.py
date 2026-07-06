"""Regression tests: AppConfig advanced fields reach process_zone_colors via runtime paths."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np

from nanoleaf_sync.config.model import AppConfig, PrivacyZone
from nanoleaf_sync.runtime.color_pipeline import (
    ColorPipelineParams,
    build_pipeline_params_from_config,
)
from nanoleaf_sync.runtime.engine_frame import process_frame


def test_build_pipeline_params_maps_advanced_fields() -> None:
    zone = PrivacyZone(x=0.1, y=0.2, w=0.3, h=0.4)
    cfg = AppConfig(
        privacy_zones=[zone],
        virtual_zone_oversample=96,
        scene_adaptive_profiles=True,
        zone_temporal_accumulation=False,
        blue_noise_dither=False,
        zone_box_filter_sampling=False,
        multi_moment_zone_colors=True,
    )
    params = build_pipeline_params_from_config(cfg)
    assert params.privacy_zones == (zone,)
    assert params.virtual_oversample == 96
    assert params.scene_adaptive_profiles is True
    assert params.zone_temporal_accumulation is False
    assert params.blue_noise_dither is False
    assert params.use_zone_box_filter is False
    assert params.multi_moment_zone_colors is True


def test_process_frame_forwards_params_object() -> None:
    captured: list[ColorPipelineParams] = []

    def _spy(**kwargs: object) -> list[tuple[int, int, int]]:
        captured.append(kwargs["params"])  # type: ignore[arg-type]
        return [(0, 0, 0)]

    params = build_pipeline_params_from_config(
        AppConfig(
            privacy_zones=[PrivacyZone(x=0.0, y=0.0, w=0.5, h=0.5)],
            zone_temporal_accumulation=False,
            blue_noise_dither=False,
            zone_box_filter_sampling=False,
            multi_moment_zone_colors=True,
            scene_adaptive_profiles=True,
            virtual_zone_oversample=48,
        )
    )
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    with patch("nanoleaf_sync.runtime.engine_frame.process_zone_colors", side_effect=_spy):
        process_frame(
            frame=frame,
            prev_smoothed_colors=[],
            zones_px=[(0, 0, 4, 4)],
            device_zone_indices=[0],
            params=params,
        )
    assert len(captured) == 1
    got = captured[0]
    assert got.privacy_zones == params.privacy_zones
    assert got.zone_temporal_accumulation is False
    assert got.blue_noise_dither is False
    assert got.use_zone_box_filter is False
    assert got.multi_moment_zone_colors is True
    assert got.scene_adaptive_profiles is True
    assert got.virtual_oversample == 48


def test_process_frame_privacy_zones_mask_sampling() -> None:
    frame = np.full((20, 20, 3), 200, dtype=np.uint8)
    zones_px = [(0, 0, 20, 4)]
    cfg = AppConfig(
        privacy_zones=[PrivacyZone(x=0.0, y=0.0, w=1.0, h=0.2)],
        zone_box_filter_sampling=True,
        zone_temporal_accumulation=False,
        blue_noise_dither=False,
    )
    params = build_pipeline_params_from_config(cfg)
    out = process_frame(
        frame=frame,
        prev_smoothed_colors=[(0, 0, 0)],
        zones_px=zones_px,
        device_zone_indices=[0],
        params=params,
        return_diagnostics=True,
    )
    assert isinstance(out, tuple)
    sampled = out[1]
    assert int(np.max(sampled[0])) == 0


def test_validate_config_normalizes_advanced_pipeline_bools() -> None:
    from nanoleaf_sync.config.normalize import validate_config

    cfg = validate_config(
        AppConfig(
            zone_temporal_accumulation=False,
            blue_noise_dither=False,
            zone_box_filter_sampling=False,
            multi_moment_zone_colors=True,
        )
    )
    assert cfg.zone_temporal_accumulation is False
    assert cfg.blue_noise_dither is False
    assert cfg.zone_box_filter_sampling is False
    assert cfg.multi_moment_zone_colors is True
    params = build_pipeline_params_from_config(cfg)
    assert params.zone_temporal_accumulation is False
    assert params.blue_noise_dither is False
    assert params.use_zone_box_filter is False
    assert params.multi_moment_zone_colors is True


def test_config_defaults_match_pipeline_params_via_builder() -> None:
    cfg = AppConfig()
    params = build_pipeline_params_from_config(cfg)
    assert params.zone_temporal_accumulation == cfg.zone_temporal_accumulation
    assert params.blue_noise_dither == cfg.blue_noise_dither
    assert params.use_zone_box_filter == cfg.zone_box_filter_sampling
    assert params.multi_moment_zone_colors == cfg.multi_moment_zone_colors
