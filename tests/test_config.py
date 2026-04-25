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


def test_app_config_has_canonical_preset_fields() -> None:
    cfg = AppConfig()
    assert cfg.layout_preset in {"edge_strip", "horizontal_debug"}
    assert cfg.edge_locality in {"tight", "balanced", "wide"}
    assert cfg.sampling_quality in {"low", "balanced", "high"}
    assert cfg.motion_preset in {"calm", "responsive", "dynamic"}
    assert cfg.color_style in {"reference", "natural", "ambient", "vivid", "punchy"}
    assert cfg.display_preset in {"sdr", "hdr", "auto"}
    assert cfg.performance_priority in {"normal", "high", "very_high_experimental"}
    assert cfg.zone_sampling_engine in {"auto", "legacy", "optimized"}


def test_validate_config_normalizes_performance_priority() -> None:
    cfg = validate_config(AppConfig(performance_priority="VERY_HIGH_EXPERIMENTAL"))
    assert cfg.performance_priority == "very_high_experimental"
    fallback = validate_config(AppConfig(performance_priority="turbo"))
    assert fallback.performance_priority == "normal"


def test_validate_config_normalizes_zone_sampling_engine() -> None:
    cfg = validate_config(AppConfig(zone_sampling_engine="LEGACY"))
    assert cfg.zone_sampling_engine == "legacy"
    fallback = validate_config(AppConfig(zone_sampling_engine="turbo"))
    assert fallback.zone_sampling_engine == "auto"
