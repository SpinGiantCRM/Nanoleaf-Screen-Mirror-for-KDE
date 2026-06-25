from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from nanoleaf_sync._coerce import as_side_counts4
from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.runtime.zone_presets import (
    apply_layout_transform,
    edge_weighted_layout,
    make_edge_weighted_zones,
    make_horizontal_zones,
)

_log = logging.getLogger(__name__)

DEFAULT_DERIVED_ZONE_COUNT = 8


def zone_distribution_from_count(zone_count: int) -> tuple[int, int, int, int]:
    total = max(4, int(zone_count))
    top = max(1, total // 4)
    right = max(1, (total - top) // 3)
    bottom = max(1, (total - top - right) // 2)
    left = max(1, total - top - right - bottom)
    remainder = total - (top + right + bottom + left)
    if remainder > 0:
        top += remainder
    return top, right, bottom, left


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
    manual_count = int(getattr(config, "device_zone_count", 0))
    if config.zones and manual_count > 0 and len(config.zones) != manual_count:
        import logging

        logging.getLogger(__name__).warning(
            "zones list length (%d) differs from device_zone_count (%d); "
            "using device_zone_count for output mapping",
            len(config.zones),
            manual_count,
        )
        return manual_count
    if config.zones:
        return len(config.zones)
    if manual_count > 0:
        return manual_count
    if detected_device_zone_count is not None and int(detected_device_zone_count) > 0:
        return int(detected_device_zone_count)
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


def _resolve_persisted_side_counts(
    config: AppConfig,
    *,
    frame_width: int | None,
    frame_height: int | None,
) -> tuple[int, int, int, int] | None:
    raw = getattr(config, "source_side_counts", None) or []
    if len(raw) == 4:
        counts = as_side_counts4(max(0, int(v)) for v in raw)
        if sum(counts) > 0:
            return counts
    zone_count = len(config.zones) if config.zones else 0
    if zone_count > 0 and frame_width and frame_height:
        layout = edge_weighted_layout(
            zone_count=zone_count,
            width=frame_width,
            height=frame_height,
            edge_locality=str(getattr(config, "edge_locality", "balanced")),
        )
        return layout.side_counts
    return None


def source_side_counts_from_config(
    config: AppConfig,
    *,
    frame_width: int | None = None,
    frame_height: int | None = None,
) -> tuple[int, int, int, int] | None:
    return _resolve_persisted_side_counts(
        config,
        frame_width=frame_width,
        frame_height=frame_height,
    )


def derive_source_zone_artifacts(
    *,
    config: AppConfig,
    detected_device_zone_count: int | None = None,
    frame_width: int | None = None,
    frame_height: int | None = None,
) -> SourceZoneArtifacts:
    if config.zones:
        source_count = len(config.zones)
        device_count = int(getattr(config, "device_zone_count", 0) or 0)
        if device_count > 0 and source_count != device_count:
            _log.warning(
                "Zone count mismatch: manual source zones=%d does not match "
                "device_zone_count=%d. Adjacent LEDs may duplicate colors. "
                "Update device_zone_count or re-run calibration.",
                source_count,
                device_count,
            )
        side_counts = _resolve_persisted_side_counts(
            config,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        return SourceZoneArtifacts(
            zones=config.zones,
            side_counts=side_counts,
            zone_order_mode="edge_strip" if side_counts is not None else None,
            edge_sampling_thickness=None,
            localized_edge_sampling_active=side_counts is not None,
            edge_locality=str(getattr(config, "edge_locality", "balanced"))
            if side_counts is not None
            else None,
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
    derived_zones = make_edge_weighted_zones(
        count,
        edge_locality=str(getattr(config, "edge_locality", "balanced")),
        width=frame_width,
        height=frame_height,
    )
    derived_zones = apply_layout_transform(
        derived_zones,
        inset=float(getattr(config, "layout_inset", 0.0)),
        scale=float(getattr(config, "layout_scale", 1.0)),
    )
    return SourceZoneArtifacts(
        zones=derived_zones,
        side_counts=layout.side_counts,
        zone_order_mode=layout.order_mode,
        edge_sampling_thickness=layout.edge_thickness,
        localized_edge_sampling_active=True,
        edge_locality=str(getattr(config, "edge_locality", "balanced")),
        frame_width=frame_width,
        frame_height=frame_height,
    )
