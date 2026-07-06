from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.runtime.calibration_resolver import (
    evaluate_device_zone_authority,
    resolve_calibration_mapping_from_config,
)


def test_corner_anchor_calibration_mapping_uses_assignments() -> None:
    cfg = AppConfig(
        calibration=CalibrationConfig(
            device_zone_count=8,
            corner_anchor_top_left=0,
            corner_anchor_top_right=2,
            corner_anchor_bottom_right=4,
            corner_anchor_bottom_left=6,
            calibration_model="corner_anchored",
        )
    )
    snap = resolve_calibration_mapping_from_config(
        config=cfg, source_zone_count=8, detected_device_zone_count=8
    )
    assert len(snap.device_to_source_indices) == 8
    assert snap.anchor_validation_ok


def test_persisted_zones_preserves_side_counts() -> None:
    from nanoleaf_sync.config.model import ZoneConfig
    from nanoleaf_sync.runtime.zone_derivation import derive_source_zone_artifacts

    cfg = AppConfig(
        zones=[ZoneConfig(x=0.0, y=0.0, w=0.1, h=0.1)] * 48,
        source_side_counts=[12, 8, 12, 16],
        device_zone_count=48,
        calibration=CalibrationConfig(
            device_zone_count=48,
            corner_anchor_top_left=0,
            corner_anchor_top_right=12,
            corner_anchor_bottom_right=24,
            corner_anchor_bottom_left=36,
        ),
    )
    artifacts = derive_source_zone_artifacts(
        config=cfg,
        frame_width=3440,
        frame_height=1440,
    )
    snap = resolve_calibration_mapping_from_config(
        config=cfg,
        source_zone_count=48,
        detected_device_zone_count=48,
        source_side_counts=artifacts.side_counts,
    )
    assert artifacts.side_counts == (12, 8, 12, 16)
    assert len(snap.device_to_source_indices) == 48


def test_duplicate_corner_anchors_fail_validation() -> None:
    cfg = AppConfig(
        device_zone_count=8,
        calibration=CalibrationConfig(
            device_zone_count=8,
            corner_anchor_top_left=0,
            corner_anchor_top_right=0,
            corner_anchor_bottom_right=4,
            corner_anchor_bottom_left=6,
        ),
    )
    snap = resolve_calibration_mapping_from_config(
        config=cfg, source_zone_count=8, detected_device_zone_count=8
    )
    assert not snap.anchor_validation_ok
    assert snap.calibration_incomplete


def test_reverse_zones_flips_mapping_order() -> None:
    forward = AppConfig(
        device_zone_count=4,
        calibration=CalibrationConfig(
            device_zone_count=4,
            corner_anchor_top_left=0,
            corner_anchor_top_right=1,
            corner_anchor_bottom_right=2,
            corner_anchor_bottom_left=3,
            reverse_zones=False,
        ),
    )
    reversed_cfg = AppConfig(
        device_zone_count=4,
        calibration=CalibrationConfig(
            device_zone_count=4,
            corner_anchor_top_left=0,
            corner_anchor_top_right=1,
            corner_anchor_bottom_right=2,
            corner_anchor_bottom_left=3,
            reverse_zones=True,
        ),
    )
    forward_snap = resolve_calibration_mapping_from_config(
        config=forward, source_zone_count=4, detected_device_zone_count=4
    )
    reverse_snap = resolve_calibration_mapping_from_config(
        config=reversed_cfg, source_zone_count=4, detected_device_zone_count=4
    )
    assert forward_snap.device_to_source_indices != reverse_snap.device_to_source_indices


def test_detected_vs_configured_strip_count_mismatch() -> None:
    cfg = AppConfig(
        device_zone_count=8,
        calibration=CalibrationConfig(device_zone_count=8),
    )
    result = evaluate_device_zone_authority(config=cfg, detected_device_zone_count=16)
    assert result.device_zone_count_mismatch
    assert result.configured_device_zone_count == 8
    assert result.detected_device_zone_count == 16
