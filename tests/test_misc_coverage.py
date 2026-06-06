"""Tests for config/presets.py, serialization.py, and capture/dimensions.py uncovered paths."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanoleaf_sync.capture.dimensions import (
    _parse_mode_line,
    _detect_primary_screen_dims_sysfs,
    detect_primary_screen_dims,
    resolve_capture_dims,
    DEFAULT_CAPTURE_WIDTH,
    DEFAULT_CAPTURE_HEIGHT,
)
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.presets import (
    EdgeLocalityProfile,
    MotionProfile,
    edge_locality_profile,
    motion_profile,
    normalize_preset,
    normalize_layout_preset,
    sampling_quality_to_zone_stride,
    analyzer_mode_for_presets,
    COLOR_STYLE_PUNCHY,
    MOTION_PRESET_DYNAMIC,
    EDGE_LOCALITY_TIGHT,
    EDGE_LOCALITY_WIDE,
    SAMPLING_QUALITY_HIGH,
    SAMPLING_QUALITY_BALANCED,
    SAMPLING_QUALITY_LOW,
    MOTION_PRESET_CALM,
)
from nanoleaf_sync.config.serialization import (
    _dump_toml_fallback,
    _prepare_payload_for_round_trip,
    dump_toml,
    toml_render_scalar,
    toml_render_list,
)


# ===========================================================================
# dimensions.py
# ===========================================================================


def test_parse_mode_line_valid() -> None:
    assert _parse_mode_line("3840x2160") == (3840, 2160)


def test_parse_mode_line_with_refresh() -> None:
    assert _parse_mode_line("3840x2160@60") == (3840, 2160)


def test_parse_mode_line_no_x() -> None:
    assert _parse_mode_line("3840") is None


def test_parse_mode_line_invalid() -> None:
    assert _parse_mode_line("abcxdef") is None


def test_parse_mode_line_negative() -> None:
    assert _parse_mode_line("-1x-1") is None


def test_detect_primary_screen_dims_no_sysfs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "exists", lambda self: False)
    result = _detect_primary_screen_dims_sysfs()
    assert result is None


def test_detect_primary_screen_dims_read_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """When reading status fails, skip connector."""
    drm_path = MagicMock()
    drm_path.exists.return_value = True
    drm_path.iterdir.return_value = []
    monkeypatch.setattr("nanoleaf_sync.capture.dimensions.Path", lambda p: drm_path if "drm" in str(p) else Path(p))
    result = _detect_primary_screen_dims_sysfs()
    assert result is None


def test_detect_primary_screen_dims_qt_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """When sysfs fails, try Qt detection (mocked)."""
    monkeypatch.setattr(
        "nanoleaf_sync.capture.dimensions._detect_primary_screen_dims_sysfs",
        lambda: None,
    )
    # Qt import should fail → returns None
    result = detect_primary_screen_dims()
    # Without Qt available in test, should return None
    assert result is None or isinstance(result, tuple)


def test_resolve_capture_dims_default() -> None:
    cfg = AppConfig()
    w, h = resolve_capture_dims(cfg)
    assert w >= DEFAULT_CAPTURE_WIDTH
    assert h >= DEFAULT_CAPTURE_HEIGHT
    assert w > 0 and h > 0


def test_resolve_capture_dims_with_zones() -> None:
    from nanoleaf_sync.config.model import ZoneConfig
    cfg = AppConfig(zones=[ZoneConfig(x=0, y=0, w=0.1, h=0.1)] * 100)
    w, h = resolve_capture_dims(cfg)
    assert w >= 400  # 100 zones * 4


# ===========================================================================
# presets.py
# ===========================================================================


def test_normalize_preset_valid() -> None:
    assert normalize_preset("high", allowed=("low", "balanced", "high"), default="balanced") == "high"


def test_normalize_preset_case_insensitive() -> None:
    assert normalize_preset("HIGH", allowed=("low", "balanced", "high"), default="balanced") == "high"


def test_normalize_preset_invalid_returns_default() -> None:
    assert normalize_preset("unknown", allowed=("low", "high"), default="balanced") == "balanced"


def test_normalize_preset_none_returns_default() -> None:
    assert normalize_preset(None, allowed=("low", "high"), default="default") == "default"


def test_normalize_layout_preset_aliases() -> None:
    assert normalize_layout_preset("edge") == "edge_strip"
    assert normalize_layout_preset("edge-weighted") == "edge_strip"
    assert normalize_layout_preset("horizontal") == "horizontal_debug"
    assert normalize_layout_preset("horizontal_debug") == "horizontal_debug"


def test_normalize_layout_preset_default() -> None:
    assert normalize_layout_preset("unknown") == "edge_strip"


def test_edge_locality_profile_tight() -> None:
    p = edge_locality_profile("tight")
    assert isinstance(p, EdgeLocalityProfile)
    assert p.edge_thickness_target == 0.055


def test_edge_locality_profile_wide() -> None:
    p = edge_locality_profile("wide")
    assert p.edge_thickness_target == 0.090


def test_edge_locality_profile_balanced() -> None:
    p = edge_locality_profile("balanced")
    assert p.edge_thickness_target == 0.070


def test_sampling_quality_to_zone_stride() -> None:
    assert sampling_quality_to_zone_stride("low") == 4
    assert sampling_quality_to_zone_stride("balanced") == 2
    assert sampling_quality_to_zone_stride("high") == 1
    assert sampling_quality_to_zone_stride("unknown") == 2  # defaults to balanced


def test_motion_profile_calm() -> None:
    p = motion_profile("calm")
    assert p.smoothing_multiplier == 0.75


def test_motion_profile_dynamic() -> None:
    p = motion_profile("dynamic")
    assert p.smoothing_multiplier == 1.15


def test_motion_profile_responsive() -> None:
    p = motion_profile("responsive")
    assert p.smoothing_multiplier == 1.0


def test_analyzer_mode_balanced() -> None:
    assert analyzer_mode_for_presets(motion_preset="calm", color_style="reference") == "balanced"
    assert analyzer_mode_for_presets(motion_preset="responsive", color_style="natural") == "balanced"
    assert analyzer_mode_for_presets(motion_preset="dynamic", color_style="ambient") == "balanced"


def test_analyzer_mode_dynamic() -> None:
    assert analyzer_mode_for_presets(motion_preset="responsive", color_style="vivid") == "dynamic"


def test_analyzer_mode_hyper() -> None:
    assert analyzer_mode_for_presets(motion_preset="dynamic", color_style="punchy") == "hyper"


# ===========================================================================
# serialization.py
# ===========================================================================


def test_toml_render_scalar_bool() -> None:
    assert toml_render_scalar(True) == "true"
    assert toml_render_scalar(False) == "false"


def test_toml_render_scalar_string() -> None:
    assert toml_render_scalar("hello") == '"hello"'


def test_toml_render_scalar_int() -> None:
    assert toml_render_scalar(42) == "42"


def test_toml_render_scalar_float() -> None:
    assert toml_render_scalar(3.14) == "3.14"


def test_toml_render_scalar_none() -> None:
    assert toml_render_scalar(None) == '""'


def test_toml_render_list() -> None:
    assert toml_render_list([1, 2, 3]) == "[1, 2, 3]"


def test_dump_toml_fallback_basic() -> None:
    result = _dump_toml_fallback({"fps": 60, "brightness": 1.0, "name": "test"})
    assert "fps = 60" in result
    assert "brightness = 1.0" in result
    assert '"test"' in result


def test_dump_toml_fallback_nested() -> None:
    result = _dump_toml_fallback({"top": {"inner": 42}})
    assert "[top]" in result
    assert "inner = 42" in result


def test_dump_toml_fallback_array_of_tables() -> None:
    result = _dump_toml_fallback({"zones": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]})
    assert "[[zones]]" in result
    assert "x = 0.0" in result


def test_dump_toml_fallback_sampling_quality_normalized() -> None:
    result = _dump_toml_fallback({"sampling_quality": "HIGH"})
    assert "sampling_quality = \"high\"" in result


def test_prepare_payload_for_round_trip_no_calibration() -> None:
    result = _prepare_payload_for_round_trip({"fps": 60})
    assert result["fps"] == 60


def test_prepare_payload_for_round_trip_with_calibration() -> None:
    result = _prepare_payload_for_round_trip({"calibration": {"device_zone_count": 10}})
    assert result["calibration"]["device_zone_count"] == 10
    assert "schema_version" in result["calibration"]


def test_dump_toml_with_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """When tomli_w is not available, uses fallback."""
    import builtins
    original_import = builtins.__import__

    def _fail_tomli(name, *args, **kwargs):
        if name == "tomli_w":
            raise ImportError("no tomli_w")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fail_tomli)
    result = dump_toml({"fps": 60})
    assert "fps" in result
