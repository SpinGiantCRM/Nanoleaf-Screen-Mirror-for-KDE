"""Tests for config/normalize.py uncovered paths: wizard state, migration, coerce_bool."""

from __future__ import annotations

import pytest

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.normalize import (
    _coerce_int,
    ConfigValidationError,
    coerce_bool,
    migrate_config_dict,
    normalize_enum,
    normalize_wizard_in_progress_state,
    validate_config,
    validate_raw_config_values,
)


# ---------------------------------------------------------------------------
# coerce_bool edge cases
# ---------------------------------------------------------------------------


def test_coerce_bool_true_bool() -> None:
    assert coerce_bool(True, False) is True


def test_coerce_bool_false_bool() -> None:
    assert coerce_bool(False, True) is False


def test_coerce_bool_none_returns_default() -> None:
    assert coerce_bool(None, True) is True
    assert coerce_bool(None, False) is False


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


def test_coerce_bool_unknown_string_returns_default() -> None:
    assert coerce_bool("unknown", True) is True
    assert coerce_bool("unknown", False) is False


def test_coerce_bool_list_returns_default() -> None:
    assert coerce_bool([1, 2, 3], True) is True


# ---------------------------------------------------------------------------
# normalize_enum
# ---------------------------------------------------------------------------


def test_normalize_enum_valid() -> None:
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
# wizard state normalization
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
# migrate_config_dict
# ---------------------------------------------------------------------------


def test_migrate_config_dict_empty() -> None:
    result = migrate_config_dict({})
    assert result["schema_version"] == 1
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
# validate_config migration path
# ---------------------------------------------------------------------------


def test_validate_config_schema_version_0_migrates() -> None:
    """Config with schema_version=0 should be migrated to version 1."""
    cfg = AppConfig(schema_version=0, fps=30)
    result = validate_config(cfg)
    assert result.schema_version == 1
    assert result.fps == 30


def test_validate_config_already_current() -> None:
    """Config already at current schema should not change version."""
    cfg = AppConfig(schema_version=1, fps=60)
    result = validate_config(cfg)
    assert result.schema_version == 1


def test_validate_config_coerces_brightness() -> None:
    cfg = AppConfig(brightness=1.5)
    result = validate_config(cfg)
    assert result.brightness == 1.0


def test_validate_config_coerces_fps() -> None:
    cfg = AppConfig(fps=200)
    result = validate_config(cfg)
    assert result.fps == 120


# ---------------------------------------------------------------------------
# _coerce_int
# ---------------------------------------------------------------------------


def test_coerce_int_valid() -> None:
    assert _coerce_int(42, 0) == 42
    assert _coerce_int("42", 0) == 42


def test_coerce_int_invalid_returns_default() -> None:
    assert _coerce_int("abc", 7) == 7
    assert _coerce_int(None, 5) == 5
    assert _coerce_int([], 3) == 3


# ---------------------------------------------------------------------------
# validate_raw_config_values
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
