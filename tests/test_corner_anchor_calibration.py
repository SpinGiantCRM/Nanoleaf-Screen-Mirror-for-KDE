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
    snap = resolve_calibration_mapping_from_config(config=cfg, source_zone_count=8, detected_device_zone_count=8)
    assert len(snap.device_to_source_indices) == 8
    assert snap.anchor_validation_ok
