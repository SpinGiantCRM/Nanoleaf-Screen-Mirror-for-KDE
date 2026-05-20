import pytest

from nanoleaf_sync.config.model import MAX_DEVICE_ZONE_COUNT, AppConfig, CalibrationConfig
from nanoleaf_sync.config.normalize import ConfigValidationError, validate_config
from nanoleaf_sync.config.store import ConfigManager
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


def test_validate_config_accepts_hex_range_usb_ids_from_toml(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("device_vid = 0x37fa\ndevice_pid = 0x8202\n", encoding="utf-8")

    cfg = ConfigManager(path=path).load()

    assert cfg.device_vid == 0x37FA
    assert cfg.device_pid == 0x8202


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("device_vid", 0),
        ("device_vid", -1),
        ("device_vid", 0x10000),
        ("device_pid", 0),
        ("device_pid", -1),
        ("device_pid", 0x10000),
    ],
)
def test_validate_config_rejects_usb_id_out_of_range(field_name: str, value: int) -> None:
    cfg = AppConfig()
    setattr(cfg, field_name, value)

    with pytest.raises(ConfigValidationError, match=field_name):
        validate_config(cfg)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("device_vid", 1.5),
        ("device_pid", "0x8202"),
        ("device_pid", True),
    ],
)
def test_validate_config_rejects_non_integer_usb_ids(field_name: str, value: object) -> None:
    cfg = AppConfig()
    setattr(cfg, field_name, value)

    with pytest.raises(ConfigValidationError, match=field_name):
        validate_config(cfg)


@pytest.mark.parametrize(
    ("field_name", "toml_value"),
    [
        ("device_vid", '"0x37fa"'),
        ("device_pid", "1.5"),
    ],
)
def test_config_load_rejects_non_integer_usb_ids(
    field_name: str, toml_value: str, tmp_path
) -> None:
    path = tmp_path / "config.toml"
    path.write_text(f"{field_name} = {toml_value}\n", encoding="utf-8")

    with pytest.raises(ConfigValidationError, match=field_name):
        ConfigManager(path=path).load()


def test_validate_config_accepts_valid_device_zone_count_bound() -> None:
    cfg = validate_config(
        AppConfig(
            device_zone_count=MAX_DEVICE_ZONE_COUNT,
            calibration=CalibrationConfig(device_zone_count=MAX_DEVICE_ZONE_COUNT),
        )
    )

    assert cfg.device_zone_count == MAX_DEVICE_ZONE_COUNT
    assert cfg.calibration.device_zone_count == MAX_DEVICE_ZONE_COUNT


@pytest.mark.parametrize(
    ("field_name", "cfg"),
    [
        ("device_zone_count", AppConfig(device_zone_count=-1)),
        (
            "calibration.device_zone_count",
            AppConfig(calibration=CalibrationConfig(device_zone_count=-1)),
        ),
    ],
)
def test_validate_config_rejects_too_small_device_zone_count(
    field_name: str, cfg: AppConfig
) -> None:
    with pytest.raises(ConfigValidationError, match=field_name):
        validate_config(cfg)


@pytest.mark.parametrize(
    ("field_name", "cfg"),
    [
        ("device_zone_count", AppConfig(device_zone_count=MAX_DEVICE_ZONE_COUNT + 1)),
        (
            "calibration.device_zone_count",
            AppConfig(calibration=CalibrationConfig(device_zone_count=MAX_DEVICE_ZONE_COUNT + 1)),
        ),
    ],
)
def test_validate_config_rejects_too_large_device_zone_count(
    field_name: str, cfg: AppConfig
) -> None:
    with pytest.raises(ConfigValidationError, match=field_name):
        validate_config(cfg)


def test_config_load_rejects_invalid_zone_count_without_defaulting(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("device_zone_count = 999999\n", encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="device_zone_count"):
        ConfigManager(path=path).load()


def test_normalize_layout_preset_maps_edge_weighted_alias_to_canonical() -> None:
    from nanoleaf_sync.config.presets import normalize_layout_preset
    from nanoleaf_sync.config.normalize import validate_config

    assert normalize_layout_preset("edge-weighted") == "edge_strip"
    assert normalize_layout_preset("edge_strip") == "edge_strip"
    assert normalize_layout_preset("Edge-Weighted") == "edge_strip"

    cfg = AppConfig(layout_preset="edge-weighted")
    result = validate_config(cfg)
    assert result.layout_preset == "edge_strip"


def test_settings_dialog_uses_canonical_layout_preset_value() -> None:
    text = open("src/nanoleaf_sync/ui/settings_dialog.py", "r", encoding="utf-8").read()
    assert '"edge-weighted"' not in text
    assert '"edge_strip"' in text


def test_display_configurator_uses_canonical_layout_preset_value() -> None:
    text = open("src/nanoleaf_sync/ui/display_configurator.py", "r", encoding="utf-8").read()
    assert '"edge-weighted"' not in text
    assert '"edge_strip"' in text
