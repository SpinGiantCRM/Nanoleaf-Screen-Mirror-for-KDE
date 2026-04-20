from __future__ import annotations

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.runtime.zone_derivation import (
    DEFAULT_DERIVED_ZONE_COUNT,
    derive_source_zones,
    effective_zone_count,
)


def test_effective_zone_count_uses_device_count_then_detected_then_default() -> None:
    assert effective_zone_count(config=AppConfig(zones=[], device_zone_count=9), detected_device_zone_count=None) == 9
    assert effective_zone_count(config=AppConfig(zones=[], device_zone_count=0), detected_device_zone_count=7) == 7
    assert (
        effective_zone_count(config=AppConfig(zones=[], device_zone_count=0), detected_device_zone_count=None)
        == DEFAULT_DERIVED_ZONE_COUNT
    )


def test_derive_source_zones_preserves_explicit_configured_zones() -> None:
    cfg = AppConfig(zones=[ZoneConfig(x=0.0, y=0.0, w=1.0, h=1.0)], zone_preset="horizontal")
    zones = derive_source_zones(config=cfg, detected_device_zone_count=10)
    assert len(zones) == 1
    assert zones == cfg.zones
