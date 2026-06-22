from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.runtime.calibration_resolver import resolve_calibration_mapping_from_config


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
