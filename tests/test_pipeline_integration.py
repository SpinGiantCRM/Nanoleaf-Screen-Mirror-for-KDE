from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.runtime.calibration_resolver import resolve_calibration_mapping_from_config
from nanoleaf_sync.runtime.zone_derivation import derive_source_zone_artifacts


def test_pipeline_mapping_uses_configured_device_zone_count() -> None:
    cfg = AppConfig(calibration=CalibrationConfig(device_zone_count=48))
    snap = resolve_calibration_mapping_from_config(config=cfg, source_zone_count=48, detected_device_zone_count=48)
    assert len(snap.device_to_source_indices) == 48


def test_pipeline_mapping_ignores_reported_count_when_manual_configured() -> None:
    cfg = AppConfig(calibration=CalibrationConfig(device_zone_count=48))
    snap = resolve_calibration_mapping_from_config(config=cfg, source_zone_count=48, detected_device_zone_count=54)
    assert len(snap.device_to_source_indices) == 48


def test_pipeline_source_zone_derivation_ignores_reported_count_when_manual_configured() -> None:
    cfg = AppConfig(device_zone_count=48, calibration=CalibrationConfig(device_zone_count=48))
    artifacts = derive_source_zone_artifacts(config=cfg, detected_device_zone_count=54, frame_width=1920, frame_height=1080)
    assert len(artifacts.zones) == 48
