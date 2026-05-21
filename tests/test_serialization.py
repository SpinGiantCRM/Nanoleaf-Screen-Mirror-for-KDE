"""Tests for config serialization helpers."""

from __future__ import annotations

import json
from copy import deepcopy

from nanoleaf_sync.config.serialization import (
    dump_toml,
    toml_render_scalar,
    toml_render_list,
    _dump_toml_fallback,
)


def test_toml_render_bool_true() -> None:
    assert toml_render_scalar(True) == "true"


def test_toml_render_bool_false() -> None:
    assert toml_render_scalar(False) == "false"


def test_toml_render_string() -> None:
    assert toml_render_scalar("hello") == json.dumps("hello")


def test_toml_render_int() -> None:
    assert toml_render_scalar(42) == "42"


def test_toml_render_float() -> None:
    assert toml_render_scalar(3.14) == "3.14"


def test_toml_render_negative_int() -> None:
    assert toml_render_scalar(-7) == "-7"


def test_toml_render_none() -> None:
    assert toml_render_scalar(None) == '""'


def test_toml_render_list() -> None:
    result = toml_render_list([1, 2, 3])
    assert result == "[1, 2, 3]"


def test_toml_render_list_strings() -> None:
    result = toml_render_list(["a", "b"])
    assert result == '["a", "b"]'


def test_toml_render_list_empty() -> None:
    assert toml_render_list([]) == "[]"


def test_fallback_dump_flat_dict() -> None:
    payload = {"fps": 60, "brightness": 0.8, "verbose": True}
    result = _dump_toml_fallback(payload)
    assert "fps = 60" in result
    assert "brightness = 0.8" in result
    assert "verbose = true" in result


def test_fallback_dump_nested_table() -> None:
    payload = {"calibration": {"device_zone_count": 48, "reverse_zones": False}}
    result = _dump_toml_fallback(payload)
    assert "[calibration]" in result
    assert "device_zone_count = 48" in result
    assert "reverse_zones = false" in result


def test_fallback_dump_list_of_tables() -> None:
    payload = {
        "zones": [
            {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.1},
            {"x": 0.5, "y": 0.0, "w": 0.5, "h": 0.1},
        ]
    }
    result = _dump_toml_fallback(payload)
    assert "[[zones]]" in result
    assert "x = 0.0" in result
    # Should appear twice (once per zone)
    assert result.count("x =") == 2


def test_fallback_dump_preserves_list_scalars() -> None:
    payload = {
        "normalized_corner_anchors": [1, 12, 24, 36],
    }
    result = _dump_toml_fallback(payload)
    assert "[1, 12, 24, 36]" in result


def test_fallback_dump_empty_dict() -> None:
    result = _dump_toml_fallback({})
    assert result == "\n"


def test_fallback_dump_sampling_quality_normalized() -> None:
    payload = {"sampling_quality": "HIGH"}
    result = _dump_toml_fallback(payload)
    # The key is special-cased to lower-case the value, then rendered as a quoted TOML string
    assert 'sampling_quality = "high"' in result


def test_fallback_dump_deeply_nested() -> None:
    payload = {
        "a": {
            "b": {"c": 1},
            "d": 2,
        }
    }
    result = _dump_toml_fallback(payload)
    assert "[a]" in result
    assert "d = 2" in result
    assert "[a.b]" in result
    assert "c = 1" in result


def test_fallback_dump_calibration_roundtrip() -> None:
    """Calibration blob should survive round-trip through fallback dump."""
    from nanoleaf_sync.config.serialization import _prepare_payload_for_round_trip

    payload = {
        "calibration": {
            "device_zone_count": 48,
            "reverse_zones": False,
            "corner_anchor_top_left": 1,
        }
    }
    prepared = _prepare_payload_for_round_trip(deepcopy(payload))
    assert prepared["calibration"]["device_zone_count"] == 48
    assert "calibration_schema_version" in prepared["calibration"]


def test_dump_toml_produces_string() -> None:
    """dump_toml should always return a string."""
    result = dump_toml({"fps": 30})
    assert isinstance(result, str)
    assert len(result) > 0


def test_dump_toml_with_calibration() -> None:
    """Full TOML dump with calibration payload."""
    payload = {
        "fps": 60,
        "device_vid": 14330,
        "calibration": {
            "corner_anchor_top_left": 1,
            "corner_anchor_top_right": 12,
            "corner_anchor_bottom_right": 24,
            "corner_anchor_bottom_left": 36,
            "device_zone_count": 48,
        },
    }
    result = dump_toml(payload)
    assert "fps" in result
    assert "calibration" in result
    assert isinstance(result, str)


def test_dump_toml_empty() -> None:
    result = dump_toml({})
    assert isinstance(result, str)
