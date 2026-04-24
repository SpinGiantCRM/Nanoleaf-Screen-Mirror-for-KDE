from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.runtime.calibration_resolver import resolve_calibration_mapping_from_config


def test_pipeline_mapping_uses_configured_device_zone_count() -> None:
    cfg = AppConfig(calibration=CalibrationConfig(device_zone_count=48))
    snap = resolve_calibration_mapping_from_config(config=cfg, source_zone_count=48, detected_device_zone_count=48)
    assert len(snap.device_to_source_indices) == 48
