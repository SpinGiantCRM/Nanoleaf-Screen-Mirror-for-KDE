"""Tests for config validation, coercion, and migration."""

from __future__ import annotations

import pytest

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.config.normalize import (
    SCHEMA_VERSION,
    ConfigValidationError,
    _coerce_int,
    _require_int_in_range,
    coerce_bool,
    migrate_config_dict,
    normalize_enum,
    normalize_wizard_in_progress_state,
    validate_config,
    validate_raw_config_values,
)

# -- _coerce_int -----------------------------------------------------------


def test_coerce_int_valid() -> None:
    assert _coerce_int(42, 0) == 42


def test_coerce_int_from_string() -> None:
    assert _coerce_int("42", 0) == 42


def test_coerce_int_invalid_fallsback() -> None:
    assert _coerce_int("abc", 99) == 99


def test_coerce_int_none_fallsback() -> None:
    assert _coerce_int(None, 99) == 99


# -- _require_int_in_range -------------------------------------------------


def test_require_int_invalid_type_raises() -> None:
    with pytest.raises(ConfigValidationError, match="must be an integer"):
        _require_int_in_range("abc", field_name="fps", minimum=1, maximum=120)


def test_require_int_bool_raises() -> None:
    with pytest.raises(ConfigValidationError, match="must be an integer"):
        _require_int_in_range(True, field_name="fps", minimum=1, maximum=120)


def test_require_int_out_of_range_raises() -> None:
    with pytest.raises(ConfigValidationError, match="must be an integer in"):
        _require_int_in_range(999, field_name="fps", minimum=1, maximum=120)


def test_require_int_valid() -> None:
    assert _require_int_in_range(60, field_name="fps", minimum=1, maximum=120) == 60


def test_require_int_boundary_min() -> None:
    assert _require_int_in_range(1, field_name="fps", minimum=1, maximum=120) == 1


def test_require_int_boundary_max() -> None:
    assert _require_int_in_range(120, field_name="fps", minimum=1, maximum=120) == 120


# -- validate_raw_config_values --------------------------------------------


def test_validate_raw_config_valid() -> None:
    validate_raw_config_values({"device_vid": 0x37FA, "device_pid": 0x8202})
    # Does not raise


def test_validate_raw_config_vid_out_of_range() -> None:
    with pytest.raises(ConfigValidationError):
        validate_raw_config_values({"device_vid": 0, "device_pid": 0x8202})


def test_validate_raw_config_pid_too_large() -> None:
    with pytest.raises(ConfigValidationError):
        validate_raw_config_values({"device_vid": 0x37FA, "device_pid": 0xFFFFF})


def test_validate_raw_config_device_zone_count_negative() -> None:
    with pytest.raises(ConfigValidationError):
        validate_raw_config_values({"device_zone_count": -1})


def test_validate_raw_config_calibration_device_zone_count() -> None:
    with pytest.raises(ConfigValidationError):
        validate_raw_config_values({"calibration": {"device_zone_count": 9999}})


# -- coerce_bool -----------------------------------------------------------


def test_coerce_bool_true_values() -> None:
    assert coerce_bool("1", False) is True
    assert coerce_bool("true", False) is True
    assert coerce_bool("TRUE", False) is True
    assert coerce_bool("yes", False) is True
    assert coerce_bool("on", False) is True


def test_coerce_bool_false_values() -> None:
    assert coerce_bool("0", True) is False
    assert coerce_bool("false", True) is False
    assert coerce_bool("FALSE", True) is False
    assert coerce_bool("no", True) is False
    assert coerce_bool("off", True) is False
    assert coerce_bool("", True) is False


def test_coerce_bool_unknown_string_returns_default() -> None:
    assert coerce_bool("maybe", True) is True
    assert coerce_bool("maybe", False) is False


def test_coerce_bool_numeric() -> None:
    assert coerce_bool(1, False) is True
    assert coerce_bool(0, True) is False
    assert coerce_bool(0.0, True) is False
    assert coerce_bool(3.14, False) is True


def test_coerce_bool_actual_bool_passthrough() -> None:
    assert coerce_bool(True, False) is True
    assert coerce_bool(False, True) is False


def test_coerce_bool_none_returns_default() -> None:
    assert coerce_bool(None, True) is True
    assert coerce_bool(None, False) is False


# -- normalize_enum --------------------------------------------------------


def test_normalize_enum_valid() -> None:
    result = normalize_enum("Rgb", allowed={"rgb": "rgb", "grb": "grb"}, default="grb")
    assert result == "rgb"


def test_normalize_enum_unknown_fallsback() -> None:
    result = normalize_enum("xyz", allowed={"rgb": "rgb", "grb": "grb"}, default="grb")
    assert result == "grb"


def test_normalize_enum_with_whitespace() -> None:
    result = normalize_enum("  rgb  ", allowed={"rgb": "rgb", "grb": "grb"}, default="grb")
    assert result == "rgb"


# -- normalize_wizard_in_progress_state ------------------------------------


def test_normalize_wizard_empty() -> None:
    assert normalize_wizard_in_progress_state("") == ""


def test_normalize_wizard_none() -> None:
    assert normalize_wizard_in_progress_state(None) == ""


def test_normalize_wizard_json() -> None:
    result = normalize_wizard_in_progress_state('{"step":2,"zones":48}')
    assert "step" in result
    assert "zones" in result


def test_normalize_wizard_non_json_text() -> None:
    result = normalize_wizard_in_progress_state("just some text")
    assert result == ""


def test_normalize_wizard_json_sorts_keys() -> None:
    result = normalize_wizard_in_progress_state('{"b":1,"a":2}')
    assert result == '{"a":2,"b":1}'


# -- migrate_config_dict ---------------------------------------------------


def test_migrate_bare_config() -> None:
    result = migrate_config_dict({})
    assert result["schema_version"] == 2
    assert isinstance(result["calibration"], dict)
    assert result["calibration"]["schema_version"] == 1
    assert result["calibration_schema_version"] == 1
    assert result["wizard_state_version"] == 1


def test_migrate_clears_wizard_state_on_version_mismatch() -> None:
    result = migrate_config_dict(
        {
            "wizard_state_version": 1,
            "wizard_in_progress_state": '{"flow_index": 1}',
        }
    )
    assert result["wizard_in_progress_state"] == ""


def test_migrate_preserves_matching_wizard_state_version() -> None:
    draft = '{"wizard_state_version": 1, "flow_index": 2}'
    result = migrate_config_dict(
        {
            "wizard_state_version": 1,
            "wizard_in_progress_state": draft,
        }
    )
    assert result["wizard_in_progress_state"] == draft


def test_migrate_preserves_existing() -> None:
    result = migrate_config_dict({"fps": 60, "brightness": 0.8})
    assert result["fps"] == 60
    assert result["brightness"] == 0.8


def test_migrate_calibration_model_default() -> None:
    result = migrate_config_dict({})
    assert result["calibration"]["calibration_model"] == "corner_anchored"


def test_migrate_keeps_existing_calibration() -> None:
    cal = {"device_zone_count": 48, "reverse_zones": True}
    result = migrate_config_dict({"calibration": cal})
    assert result["calibration"]["device_zone_count"] == 48
    assert result["calibration"]["reverse_zones"] is True


# ---------------------------------------------------------------------------
# Extended: coerce_bool edge cases (from test_normalize_extended)
# ---------------------------------------------------------------------------


def test_coerce_bool_int() -> None:
    assert coerce_bool(1, False) is True
    assert coerce_bool(0, True) is False
    assert coerce_bool(42, False) is True


def test_coerce_bool_float() -> None:
    assert coerce_bool(1.0, False) is True
    assert coerce_bool(0.0, True) is False


def test_coerce_bool_string_true_values() -> None:
    for val in ("1", "true", "True", "TRUE", "yes", "YES", "on", "ON"):
        assert coerce_bool(val, False) is True


def test_coerce_bool_string_false_values() -> None:
    for val in ("0", "false", "False", "no", "off", ""):
        assert coerce_bool(val, True) is False


def test_coerce_bool_list_returns_default() -> None:
    assert coerce_bool([1, 2, 3], True) is True


# ---------------------------------------------------------------------------
# Extended: normalize_enum
# ---------------------------------------------------------------------------


def test_normalize_enum_valid_extended() -> None:
    result = normalize_enum("foo", allowed={"foo": "FOO", "bar": "BAR"}, default="default")
    assert result == "FOO"


def test_normalize_enum_case_insensitive() -> None:
    result = normalize_enum("BAR", allowed={"foo": "FOO", "bar": "BAR"}, default="default")
    assert result == "BAR"


def test_normalize_enum_unknown_returns_default() -> None:
    result = normalize_enum("unknown", allowed={"foo": "FOO"}, default="default")
    assert result == "default"


def test_normalize_enum_whitespace_handling() -> None:
    result = normalize_enum("  foo  ", allowed={"foo": "FOO"}, default="default")
    assert result == "FOO"


# ---------------------------------------------------------------------------
# Extended: wizard state normalization
# ---------------------------------------------------------------------------


def test_normalize_wizard_state_empty() -> None:
    assert normalize_wizard_in_progress_state(None) == ""
    assert normalize_wizard_in_progress_state("") == ""
    assert normalize_wizard_in_progress_state("   ") == ""


def test_normalize_wizard_state_valid_json() -> None:
    result = normalize_wizard_in_progress_state('{"flow_index": 1, "b": 2}')
    assert '"flow_index"' in result
    assert '"b"' in result


def test_normalize_wizard_state_invalid_json() -> None:
    """Invalid JSON should be cleared."""
    result = normalize_wizard_in_progress_state("{not valid json")
    assert result == ""


def test_normalize_wizard_state_non_dict_json() -> None:
    """JSON that is not a dict should be cleared."""
    result = normalize_wizard_in_progress_state("[1, 2, 3]")
    assert result == ""


def test_normalize_wizard_state_oversized() -> None:
    """State exceeding 64KB limit should be cleared."""
    large = '{"key": "' + ("x" * 70_000) + '"}'
    result = normalize_wizard_in_progress_state(large)
    assert result == ""


def test_normalize_wizard_state_sorts_keys() -> None:
    result = normalize_wizard_in_progress_state('{"b": 2, "a": 1}')
    assert result.index("a") < result.index("b")


# ---------------------------------------------------------------------------
# Extended: migrate_config_dict
# ---------------------------------------------------------------------------


def test_migrate_config_dict_empty() -> None:
    result = migrate_config_dict({})
    assert result["schema_version"] == 2
    assert "calibration" in result
    assert result["calibration"]["schema_version"] == 1
    assert result["calibration"]["calibration_model"] == "corner_anchored"


def test_migrate_config_dict_preserves_existing() -> None:
    result = migrate_config_dict({"schema_version": 1, "fps": 60})
    assert result["fps"] == 60
    assert result["schema_version"] == 1


def test_migrate_config_dict_adds_calibration_model() -> None:
    result = migrate_config_dict({"calibration": {"device_zone_count": 10}})
    assert result["calibration"]["calibration_model"] == "corner_anchored"
    assert result["calibration"]["device_zone_count"] == 10


# ---------------------------------------------------------------------------
# Extended: validate_config migration path
# ---------------------------------------------------------------------------


def test_validate_config_schema_version_0_migrates() -> None:
    """Config with schema_version=0 should be migrated to the current schema."""
    cfg = AppConfig(schema_version=0, fps=30)
    result = validate_config(cfg)
    assert result.schema_version == SCHEMA_VERSION
    assert result.fps == 30


def test_validate_config_schema_version_1_preserves_device_zone_count_raw() -> None:
    cfg = AppConfig(
        schema_version=1,
        device_zone_count=48,
        calibration=CalibrationConfig(device_zone_count=48),
    )
    result = validate_config(cfg)
    assert result.schema_version == SCHEMA_VERSION
    assert result.device_zone_count_raw == 48


def test_validate_config_already_current() -> None:
    """Config already at current schema should not change version."""
    cfg = AppConfig(schema_version=SCHEMA_VERSION, fps=60)
    result = validate_config(cfg)
    assert result.schema_version == SCHEMA_VERSION


def test_validate_config_coerces_brightness() -> None:
    cfg = AppConfig(brightness=1.5)
    result = validate_config(cfg)
    assert result.brightness == 1.0


def test_validate_config_coerces_fps() -> None:
    cfg = AppConfig(fps=200)
    result = validate_config(cfg)
    assert result.fps == 120


# ---------------------------------------------------------------------------
# Extended: _coerce_int
# ---------------------------------------------------------------------------


def test_coerce_int_valid_extended() -> None:
    assert _coerce_int(42, 0) == 42
    assert _coerce_int("42", 0) == 42


def test_coerce_int_invalid_returns_default() -> None:
    assert _coerce_int("abc", 7) == 7
    assert _coerce_int(None, 5) == 5
    assert _coerce_int([], 3) == 3


# ---------------------------------------------------------------------------
# Extended: validate_raw_config_values
# ---------------------------------------------------------------------------


def test_validate_raw_config_values_valid() -> None:
    validate_raw_config_values(
        {"device_vid": 0x37FA, "device_pid": 0x8202, "device_zone_count": 10}
    )


def test_validate_raw_config_values_vid_out_of_range() -> None:
    with pytest.raises(ConfigValidationError):
        validate_raw_config_values({"device_vid": 0})


def test_validate_raw_config_values_pid_out_of_range() -> None:
    with pytest.raises(ConfigValidationError):
        validate_raw_config_values({"device_pid": 0x10000})


def test_validate_raw_config_values_zone_count_out_of_range() -> None:
    with pytest.raises(ConfigValidationError):
        validate_raw_config_values({"device_zone_count": 99999})


def test_validate_raw_config_values_calibration_zone_count() -> None:
    with pytest.raises(ConfigValidationError):
        validate_raw_config_values({"calibration": {"device_zone_count": 99999}})


def test_validate_raw_config_values_boolean_vid_rejected() -> None:
    with pytest.raises(ConfigValidationError):
        validate_raw_config_values({"device_vid": True})
