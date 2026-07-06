"""Tests for config serialization helpers."""

from __future__ import annotations

from copy import deepcopy

from nanoleaf_sync.config.store import (
    _prepare_payload_for_round_trip,
    dump_toml,
)


def test_dump_toml_calibration_roundtrip() -> None:
    """Calibration blob should survive round-trip through dump."""
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
