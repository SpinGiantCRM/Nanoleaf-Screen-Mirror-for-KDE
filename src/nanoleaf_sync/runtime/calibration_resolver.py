from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from nanoleaf_sync.color.zone_mapper import resolve_device_zone_indices
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.anchor_calibration import derive_anchor_zone_map, validate_corner_anchors


@dataclass(frozen=True)
class CalibrationMappingSnapshot:
    device_to_source_indices: list[int]
    strategy: str
    calibration_model: str
    anchor_validation_errors: tuple[str, ...]

    @property
    def anchor_validation_ok(self) -> bool:
        return not self.anchor_validation_errors


def _normalize_anchor(value: int | None) -> int | None:
    if value is None:
        return None
    parsed = int(value)
    return parsed if parsed >= 0 else None


def resolve_calibration_mapping(
    *,
    zone_count: int,
    device_zone_count: int,
    zone_offset: int,
    reverse_zones: bool,
    manual_mapping_enabled: bool,
    explicit_zone_map: Sequence[int] | None = None,
    corner_zone_offsets: Sequence[int] | None = None,
    corner_anchor_top_left: int = -1,
    corner_anchor_top_right: int = -1,
    corner_anchor_bottom_right: int = -1,
    corner_anchor_bottom_left: int = -1,
    calibration_model: str = "offset_direction",
) -> CalibrationMappingSnapshot:
    normalized_model = str(calibration_model).strip().lower().replace("-", "_")
    anchors = {
        "top_left": _normalize_anchor(corner_anchor_top_left),
        "top_right": _normalize_anchor(corner_anchor_top_right),
        "bottom_right": _normalize_anchor(corner_anchor_bottom_right),
        "bottom_left": _normalize_anchor(corner_anchor_bottom_left),
    }

    anchor_validation_errors: tuple[str, ...] = ()
    selected_explicit_map: list[int] | None = None
    strategy = "offset_direction"

    if normalized_model == "corner_anchored":
        anchor_validation = validate_corner_anchors(anchors=anchors, device_zone_count=device_zone_count)
        if anchor_validation.valid:
            selected_explicit_map = derive_anchor_zone_map(
                zone_count=zone_count,
                device_zone_count=device_zone_count,
                anchors=anchors,
            ).explicit_zone_map
            strategy = "corner_anchored"
        else:
            anchor_validation_errors = tuple(anchor_validation.errors)

    if selected_explicit_map is None and manual_mapping_enabled and explicit_zone_map:
        selected_explicit_map = [int(i) for i in explicit_zone_map]
        strategy = "explicit_manual_map"

    normalized_device_zone_count = int(device_zone_count)
    if normalized_device_zone_count <= 0:
        normalized_device_zone_count = 1

    mapping = resolve_device_zone_indices(
        max(1, int(zone_count)),
        device_zone_count=normalized_device_zone_count,
        zone_offset=int(zone_offset),
        reverse=bool(reverse_zones),
        manual_mapping_enabled=bool(selected_explicit_map),
        explicit_zone_map=selected_explicit_map,
        corner_zone_offsets=list(corner_zone_offsets) if corner_zone_offsets else None,
    )
    return CalibrationMappingSnapshot(
        device_to_source_indices=mapping,
        strategy=strategy,
        calibration_model=normalized_model,
        anchor_validation_errors=anchor_validation_errors,
    )


def resolve_calibration_mapping_from_config(
    *,
    config: AppConfig,
    source_zone_count: int,
    detected_device_zone_count: int | None = None,
) -> CalibrationMappingSnapshot:
    configured_device_zone_count = int(getattr(config, "device_zone_count", 0))
    device_zone_count = configured_device_zone_count if configured_device_zone_count > 0 else max(1, int(source_zone_count))
    if detected_device_zone_count and configured_device_zone_count <= 0:
        device_zone_count = max(1, int(detected_device_zone_count))
    return resolve_calibration_mapping(
        zone_count=source_zone_count,
        device_zone_count=device_zone_count,
        zone_offset=int(getattr(config, "zone_offset", 0)),
        reverse_zones=bool(getattr(config, "reverse_zones", False)),
        manual_mapping_enabled=bool(getattr(config, "manual_mapping_enabled", False)),
        explicit_zone_map=getattr(config, "explicit_zone_map", None) or None,
        corner_zone_offsets=(
            getattr(config, "corner_zone_offsets", None)
            if bool(getattr(config, "corner_offsets_enabled", False))
            else None
        ),
        corner_anchor_top_left=int(getattr(config, "corner_anchor_top_left", -1)),
        corner_anchor_top_right=int(getattr(config, "corner_anchor_top_right", -1)),
        corner_anchor_bottom_right=int(getattr(config, "corner_anchor_bottom_right", -1)),
        corner_anchor_bottom_left=int(getattr(config, "corner_anchor_bottom_left", -1)),
        calibration_model=str(getattr(config, "calibration_model", "offset_direction")),
    )
