from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.config.normalize import validate_config
from nanoleaf_sync.config.serialization import dump_toml


def test_effective_calibration_prefers_nested_block() -> None:
    cfg = AppConfig(calibration=CalibrationConfig(device_zone_count=48, reverse_zones=True))
    out = cfg.effective_calibration()
    assert out.device_zone_count == 48
    assert out.reverse_zones is True


def test_validate_config_keeps_corner_anchored_schema() -> None:
    cfg = validate_config(AppConfig(calibration=CalibrationConfig(calibration_model="manual_map")))
    assert cfg.calibration.calibration_model == "corner_anchored"


def test_dump_toml_keeps_calibration_block() -> None:
    data = {
        "calibration_schema_version": 1,
        "calibration": {
            "schema_version": 1,
            "calibration_schema_version": 1,
            "calibration_model": "corner_anchored",
            "device_zone_count": 48,
            "reverse_zones": False,
        },
    }
    rendered = dump_toml(data)
    assert "[calibration]" in rendered
    assert "device_zone_count" in rendered
