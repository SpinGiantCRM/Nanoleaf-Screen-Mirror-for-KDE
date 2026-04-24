from __future__ import annotations

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.runtime.zone_derivation import (
    DEFAULT_DERIVED_ZONE_COUNT,
    derive_source_zone_artifacts,
    derive_source_zones,
    effective_zone_count,
)


def test_default_layout_preset_is_edge_strip() -> None:
    assert AppConfig().layout_preset == "edge_strip"


def test_effective_zone_count_uses_manual_device_count_then_default() -> None:
    assert effective_zone_count(config=AppConfig(zones=[], device_zone_count=9), detected_device_zone_count=None) == 9
    assert effective_zone_count(config=AppConfig(zones=[], device_zone_count=0), detected_device_zone_count=7) == DEFAULT_DERIVED_ZONE_COUNT
    assert effective_zone_count(config=AppConfig(zones=[], device_zone_count=0), detected_device_zone_count=None) == DEFAULT_DERIVED_ZONE_COUNT


def test_derive_source_zones_preserves_explicit_configured_zones() -> None:
    cfg = AppConfig(zones=[ZoneConfig(x=0.0, y=0.0, w=1.0, h=1.0)], layout_preset="horizontal_debug")
    zones = derive_source_zones(config=cfg, detected_device_zone_count=10)
    assert len(zones) == 1
    assert zones == cfg.zones


def test_default_edge_source_zone_count_follows_device_zone_count() -> None:
    cfg = AppConfig(zones=[], layout_preset="edge_strip", device_zone_count=48)
    zones = derive_source_zones(config=cfg, detected_device_zone_count=None)
    assert len(zones) == 48


def test_edge_strip_48_zone_layout_covers_all_perimeter_sides() -> None:
    cfg = AppConfig(zones=[], layout_preset="edge_strip", device_zone_count=48)
    zones = derive_source_zones(config=cfg, detected_device_zone_count=None, frame_width=1920, frame_height=1080)
    artifacts = derive_source_zone_artifacts(config=cfg, detected_device_zone_count=None, frame_width=1920, frame_height=1080)
    top, right, bottom, _left = artifacts.side_counts or (0, 0, 0, 0)
    assert len(zones) == 48
    assert all(zone.y == 0.0 for zone in zones[:top])
    assert all(zone.x > 0.75 for zone in zones[top : top + right])
    assert all(zone.y > 0.90 for zone in zones[top + right : top + right + bottom])
    assert all(zone.x == 0.0 for zone in zones[top + right + bottom :])


def test_runtime_preview_reports_aspect_weighted_side_counts() -> None:
    cfg = AppConfig(zones=[], layout_preset="edge_strip", edge_locality="tight", device_zone_count=48)
    artifacts = derive_source_zone_artifacts(config=cfg, detected_device_zone_count=48, frame_width=1920, frame_height=1080)
    preview = artifacts.diagnostics_text(source_mode="auto-derived", device_zone_count=48)
    assert "source zones: 48 | strip zones: 48" in preview
    assert "frame: 1920x1080" in preview
    assert "side counts: top/right/bottom/left=15/9/15/9" in preview
    assert "zone order mode: continuous_perimeter" in preview
    assert "localized edge sampling: on" in preview
    assert "edge locality: tight" in preview
