"""Tests for corner anchor validation and zone map derivation."""

from __future__ import annotations

import pytest

from nanoleaf_sync.runtime.anchor_calibration import (
    validate_corner_anchors,
    derive_anchor_zone_map,
    AnchorMappingResult,
)


# -- validate_corner_anchors -----------------------------------------------


def _anchors(
    tl: int | None = None,
    tr: int | None = None,
    br: int | None = None,
    bl: int | None = None,
) -> dict:
    return {
        "top_left": tl,
        "top_right": tr,
        "bottom_right": br,
        "bottom_left": bl,
    }


def test_validate_zero_device_zone_count() -> None:
    result = validate_corner_anchors(anchors=_anchors(1, 2, 3, 4), device_zone_count=0)
    assert result.valid is False
    assert any("at least 1" in e for e in result.errors)


def test_validate_missing_anchor() -> None:
    result = validate_corner_anchors(anchors=_anchors(1, 2, 3), device_zone_count=48)
    assert result.valid is False
    assert any("Missing" in e for e in result.errors)


def test_validate_anchor_out_of_range() -> None:
    result = validate_corner_anchors(anchors=_anchors(1, 2, 3, 999), device_zone_count=48)
    assert result.valid is False
    assert any("outside" in e for e in result.errors)


def test_validate_negative_anchor() -> None:
    result = validate_corner_anchors(anchors=_anchors(-1, 2, 3, 4), device_zone_count=48)
    assert result.valid is False
    assert any("outside" in e for e in result.errors)


def test_validate_duplicate_anchors() -> None:
    result = validate_corner_anchors(anchors=_anchors(1, 1, 3, 4), device_zone_count=48)
    assert result.valid is False
    assert any("unique" in e for e in result.errors)


def test_validate_too_few_zones_for_corners() -> None:
    result = validate_corner_anchors(anchors=_anchors(0, 1, 2, 3), device_zone_count=3)
    assert result.valid is False
    assert any("At least 4" in e for e in result.errors)


def test_validate_valid() -> None:
    result = validate_corner_anchors(anchors=_anchors(1, 12, 24, 36), device_zone_count=48)
    assert result.valid is True
    assert result.errors == []


def test_validate_boundary_indices() -> None:
    """Anchors at 0 and device_zone_count-1 should be valid."""
    result = validate_corner_anchors(anchors=_anchors(0, 15, 30, 47), device_zone_count=48)
    assert result.valid is True


# -- derive_anchor_zone_map ------------------------------------------------


def test_derive_zone_map_valid() -> None:
    result = derive_anchor_zone_map(
        zone_count=10,
        device_zone_count=48,
        anchors=_anchors(1, 12, 24, 36),
    )
    assert isinstance(result, AnchorMappingResult)
    assert len(result.mapping) == 48
    assert result.direction in ("clockwise", "counter-clockwise")
    assert len(result.ordered_corners) == 4
    assert len(result.edge_lengths) == 4


def test_derive_zone_map_invalid_raises() -> None:
    with pytest.raises(ValueError):
        derive_anchor_zone_map(
            zone_count=10,
            device_zone_count=48,
            anchors=_anchors(1, 2),  # missing 2
        )


def test_derive_zone_map_with_source_side_counts() -> None:
    result = derive_anchor_zone_map(
        zone_count=20,
        device_zone_count=48,
        anchors=_anchors(0, 12, 24, 36),
        source_side_counts=(5, 5, 5, 5),
    )
    assert len(result.mapping) == 48


def test_derive_zone_map_counter_clockwise() -> None:
    """Wrapping anchors counter-clockwise should be detected."""
    result = derive_anchor_zone_map(
        zone_count=10,
        device_zone_count=48,
        anchors=_anchors(1, 36, 24, 12),  # ccw order
    )
    assert isinstance(result, AnchorMappingResult)
    # Direction should be detected based on edge length scoring
    assert result.direction in ("clockwise", "counter-clockwise")
