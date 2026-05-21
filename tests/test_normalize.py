"""Tests for config validation, coercion, and migration."""

from __future__ import annotations

import pytest

from nanoleaf_sync.config.normalize import (
    coerce_bool,
    normalize_enum,
    normalize_wizard_in_progress_state,
    migrate_config_dict,
    validate_raw_config_values,
    ConfigValidationError,
    _coerce_int,
    _require_int_in_range,
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
    assert result == "just some text"


def test_normalize_wizard_json_sorts_keys() -> None:
    result = normalize_wizard_in_progress_state('{"b":1,"a":2}')
    assert result == '{"a":2,"b":1}'


# -- migrate_config_dict ---------------------------------------------------


def test_migrate_bare_config() -> None:
    result = migrate_config_dict({})
    assert result["schema_version"] == 1
    assert isinstance(result["calibration"], dict)
    assert result["calibration"]["schema_version"] == 1
    assert result["calibration_schema_version"] == 1


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
