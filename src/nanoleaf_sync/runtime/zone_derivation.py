from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.ui.zone_presets import (
    edge_weighted_layout,
    make_edge_weighted_zones,
    make_horizontal_zones,
)

DEFAULT_DERIVED_ZONE_COUNT = 8


@dataclass(frozen=True)
class SourceZoneArtifacts:
    zones: Sequence[ZoneConfig]
    side_counts: tuple[int, int, int, int] | None
    zone_order_mode: str | None
    edge_sampling_thickness: float | None
    edge_locality: str | None
    localized_edge_sampling_active: bool
    frame_width: int | None
    frame_height: int | None

    @property
    def aspect_ratio(self) -> float | None:
        if not self.frame_width or not self.frame_height:
            return None
        return float(self.frame_width) / float(self.frame_height)

    def diagnostics_text(self, *, source_mode: str, device_zone_count: int) -> str:
        dims = (
            f"{self.frame_width}x{self.frame_height} ({self.aspect_ratio:.3f}:1)"
            if self.frame_width and self.frame_height and self.aspect_ratio
            else "unknown"
        )
        side_text = "n/a"
        if self.side_counts is not None:
            top, right, bottom, left = self.side_counts
            side_text = f"top/right/bottom/left={top}/{right}/{bottom}/{left}"
        thickness = (
            f"{self.edge_sampling_thickness:.3f}"
            if self.edge_sampling_thickness is not None
            else "n/a"
        )
        return (
            f"source zones: {len(self.zones)} | strip zones: {device_zone_count} | "
            f"frame: {dims} | side counts: {side_text} | "
            f"zone order mode: {self.zone_order_mode or 'n/a'} | "
            f"edge sampling thickness: {thickness} | "
            f"localized edge sampling: {'on' if self.localized_edge_sampling_active else 'off'} | "
            f"edge locality: {self.edge_locality or 'n/a'} | source mode: {source_mode}"
        )


def effective_zone_count(
    *,
    config: AppConfig,
    detected_device_zone_count: int | None = None,
) -> int:
    _ = detected_device_zone_count
    if config.zones:
        return len(config.zones)
    if int(getattr(config, "device_zone_count", 0)) > 0:
        return int(config.device_zone_count)
    return DEFAULT_DERIVED_ZONE_COUNT


def derive_source_zones(
    *,
    config: AppConfig,
    detected_device_zone_count: int | None = None,
    frame_width: int | None = None,
    frame_height: int | None = None,
) -> Sequence[ZoneConfig]:
    return derive_source_zone_artifacts(
        config=config,
        detected_device_zone_count=detected_device_zone_count,
        frame_width=frame_width,
        frame_height=frame_height,
    ).zones


def derive_source_zone_artifacts(
    *,
    config: AppConfig,
    detected_device_zone_count: int | None = None,
    frame_width: int | None = None,
    frame_height: int | None = None,
) -> SourceZoneArtifacts:
    if config.zones:
        return SourceZoneArtifacts(
            zones=config.zones,
            side_counts=None,
            zone_order_mode=None,
            edge_sampling_thickness=None,
            localized_edge_sampling_active=False,
            edge_locality=None,
            frame_width=frame_width,
            frame_height=frame_height,
        )

    count = max(
        1,
        effective_zone_count(config=config, detected_device_zone_count=detected_device_zone_count),
    )
    preset = str(getattr(config, "layout_preset", "edge_strip"))
    if preset == "horizontal_debug":
        return SourceZoneArtifacts(
            zones=make_horizontal_zones(count),
            side_counts=None,
            zone_order_mode="horizontal",
            edge_sampling_thickness=None,
            localized_edge_sampling_active=False,
            edge_locality=None,
            frame_width=frame_width,
            frame_height=frame_height,
        )
    layout = edge_weighted_layout(
        zone_count=count,
        width=frame_width,
        height=frame_height,
        edge_locality=str(getattr(config, "edge_locality", "balanced")),
    )
    return SourceZoneArtifacts(
        zones=make_edge_weighted_zones(
            count,
            edge_locality=str(getattr(config, "edge_locality", "balanced")),
            width=frame_width,
            height=frame_height,
        ),
        side_counts=layout.side_counts,
        zone_order_mode=layout.order_mode,
        edge_sampling_thickness=layout.edge_thickness,
        localized_edge_sampling_active=True,
        edge_locality=str(getattr(config, "edge_locality", "balanced")),
        frame_width=frame_width,
        frame_height=frame_height,
    )
