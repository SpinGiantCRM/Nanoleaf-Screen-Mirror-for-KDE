from __future__ import annotations

from typing import Sequence

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones, make_horizontal_zones

DEFAULT_DERIVED_ZONE_COUNT = 8


def effective_zone_count(
    *,
    config: AppConfig,
    detected_device_zone_count: int | None = None,
) -> int:
    if config.zones:
        return len(config.zones)
    if int(getattr(config, "device_zone_count", 0)) > 0:
        return int(config.device_zone_count)
    if int(detected_device_zone_count or 0) > 0:
        return int(detected_device_zone_count)
    return DEFAULT_DERIVED_ZONE_COUNT


def derive_source_zones(
    *,
    config: AppConfig,
    detected_device_zone_count: int | None = None,
) -> Sequence[ZoneConfig]:
    if config.zones:
        return config.zones

    count = max(1, effective_zone_count(config=config, detected_device_zone_count=detected_device_zone_count))
    preset = str(getattr(config, "zone_preset", "edge-weighted"))
    if preset == "horizontal":
        return make_horizontal_zones(count)
    return make_edge_weighted_zones(count, edge_sampling_thickness=float(config.edge_sampling_thickness))
