from __future__ import annotations

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.normalize import validate_config
from nanoleaf_sync.config.presets import (
    PERFORMANCE_PROFILE_BALANCED,
    PERFORMANCE_PROFILE_CUSTOM,
    PERFORMANCE_PROFILE_PERFORMANCE,
    PERFORMANCE_PROFILE_QUALITY,
    detect_performance_profile,
    performance_profile_bundle,
)


def test_performance_profile_bundles_match_settings_defaults() -> None:
    balanced = performance_profile_bundle(PERFORMANCE_PROFILE_BALANCED)
    assert balanced.fps == 60
    assert balanced.sampling_quality == "balanced"
    assert balanced.edge_locality == "balanced"
    assert balanced.light_spread == "balanced"
    assert balanced.motion_preset == "responsive"
    assert balanced.smoothing_percent == 50
    assert balanced.smoothing_speed_percent == 75

    performance = performance_profile_bundle(PERFORMANCE_PROFILE_PERFORMANCE)
    assert performance.fps == 30
    assert performance.sampling_quality == "low"

    quality = performance_profile_bundle(PERFORMANCE_PROFILE_QUALITY)
    assert quality.sampling_quality == "high"
    assert quality.edge_locality == "wide"
    assert quality.smoothing_percent == 35
    assert quality.smoothing_speed_percent == 120


def test_detect_performance_profile_matches_default_config() -> None:
    cfg = validate_config(AppConfig())
    detected = detect_performance_profile(
        fps=int(cfg.fps),
        sampling_quality=str(cfg.sampling_quality),
        edge_locality=str(cfg.edge_locality),
        light_spread=str(cfg.light_spread),
        motion_preset=str(cfg.motion_preset),
        smoothing=float(cfg.smoothing),
        smoothing_speed=float(cfg.smoothing_speed),
    )
    assert detected == PERFORMANCE_PROFILE_BALANCED


def test_detect_performance_profile_returns_none_for_drift() -> None:
    cfg = validate_config(AppConfig())
    detected = detect_performance_profile(
        fps=int(cfg.fps),
        sampling_quality="high",
        edge_locality=str(cfg.edge_locality),
        light_spread=str(cfg.light_spread),
        motion_preset=str(cfg.motion_preset),
        smoothing=float(cfg.smoothing),
        smoothing_speed=float(cfg.smoothing_speed),
    )
    assert detected is None


def test_validate_config_preserves_custom_performance_profile() -> None:
    cfg = validate_config(AppConfig(performance_profile=PERFORMANCE_PROFILE_CUSTOM))
    assert cfg.performance_profile == PERFORMANCE_PROFILE_CUSTOM
