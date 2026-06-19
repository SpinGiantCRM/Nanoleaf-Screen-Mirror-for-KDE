"""Tests for capture dimension detection and resolution."""

from __future__ import annotations

from nanoleaf_sync.capture.dimensions import (
    DEFAULT_CAPTURE_HEIGHT,
    DEFAULT_CAPTURE_WIDTH,
    _parse_mode_line,
    resolve_capture_dims,
)

# -- _parse_mode_line ------------------------------------------------------


def test_parse_standard_mode() -> None:
    result = _parse_mode_line("3840x2160")
    assert result == (3840, 2160)


def test_parse_mode_with_refresh() -> None:
    result = _parse_mode_line("1920x1080@60")
    assert result == (1920, 1080)


def test_parse_mode_with_whitespace() -> None:
    result = _parse_mode_line("  2560x1440@144  ")
    assert result == (2560, 1440)


def test_parse_mode_no_x_separator() -> None:
    assert _parse_mode_line("3840-2160") is None


def test_parse_mode_empty() -> None:
    assert _parse_mode_line("") is None


def test_parse_mode_non_numeric() -> None:
    assert _parse_mode_line("abcxdef") is None


def test_parse_mode_negative_values() -> None:
    assert _parse_mode_line("-1x1080") is None
    assert _parse_mode_line("1920x-1") is None


def test_parse_mode_just_refresh() -> None:
    assert _parse_mode_line("@60") is None


def test_parse_mode_extra_at_signs() -> None:
    """Only first @ is the separator."""
    result = _parse_mode_line("1920x1080@60@something")
    assert result == (1920, 1080)


# -- resolve_capture_dims --------------------------------------------------


def test_resolve_capture_dims_mock_config_no_zones() -> None:
    """Without zones or detected screen, returns default dimensions."""
    from nanoleaf_sync.config.model import AppConfig

    cfg = AppConfig(zones=[])
    w, h = resolve_capture_dims(cfg)
    assert w >= 160
    assert h >= 90
    assert w == DEFAULT_CAPTURE_WIDTH
    assert h == DEFAULT_CAPTURE_HEIGHT


def test_resolve_capture_dims_wide_zone_count() -> None:
    """Many zones should increase the minimum width."""
    from nanoleaf_sync.config.model import AppConfig, ZoneConfig

    zones = [ZoneConfig(x=0.0, y=0.0, w=1.0, h=0.1) for _ in range(200)]
    cfg = AppConfig(zones=zones)
    w, h = resolve_capture_dims(cfg)
    assert w >= 200 * 4  # zone_count * 4
    assert w >= 160
    assert h >= 90


def test_resolve_capture_dims_aspect_ratio_16_9() -> None:
    """Height should be at least 9/16 of width."""
    from nanoleaf_sync.config.model import AppConfig

    cfg = AppConfig(zones=[])
    w, h = resolve_capture_dims(cfg)
    assert h >= (w * 9) // 16
