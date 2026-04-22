from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from nanoleaf_sync.color.zone_mapper import resolve_device_zone_indices
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.anchor_calibration import derive_anchor_zone_map, validate_corner_anchors


@dataclass(frozen=True)
class CalibrationMappingSnapshot:
    device_to_source_indices: list[int]
    mode: str
    direction: str
    validation_warnings: tuple[str, ...]
    calibration_model: str
    strategy: str

    @property
    def anchor_validation_ok(self) -> bool:
        return not self.validation_warnings

    @property
    def anchor_validation_errors(self) -> tuple[str, ...]:
        # Backwards-compatible alias for older call-sites/tests.
        return self.validation_warnings


@dataclass(frozen=True)
class CalibrationResolverContext:
    source_zone_count: int
    effective_device_zone_count: int
    detected_device_zone_count: int | None = None


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

    validation_warnings: tuple[str, ...] = ()
    selected_explicit_map: list[int] | None = None
    strategy = "offset_direction"
    direction = "counter-clockwise" if bool(reverse_zones) else "clockwise"

    if normalized_model == "corner_anchored":
        anchor_validation = validate_corner_anchors(anchors=anchors, device_zone_count=device_zone_count)
        if anchor_validation.valid:
            anchor_map = derive_anchor_zone_map(
                zone_count=zone_count,
                device_zone_count=device_zone_count,
                anchors=anchors,
            )
            selected_explicit_map = anchor_map.explicit_zone_map
            strategy = "corner_anchored"
            direction = anchor_map.direction
        else:
            validation_warnings = tuple(anchor_validation.errors)

    if selected_explicit_map is None and manual_mapping_enabled and explicit_zone_map:
        selected_explicit_map = [int(i) for i in explicit_zone_map]
        strategy = "explicit_manual_map"
        direction = "manual"

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
        mode=strategy,
        direction=direction,
        validation_warnings=validation_warnings,
        strategy=strategy,
        calibration_model=normalized_model,
    )


def resolve_calibration_mapping_from_config(
    *,
    config: AppConfig,
    source_zone_count: int,
    detected_device_zone_count: int | None = None,
) -> CalibrationMappingSnapshot:
    calibration = config.effective_calibration()
    configured_device_zone_count = int(getattr(calibration, "device_zone_count", 0))
    context = CalibrationResolverContext(
        source_zone_count=int(source_zone_count),
        effective_device_zone_count=(configured_device_zone_count if configured_device_zone_count > 0 else max(1, int(source_zone_count))),
        detected_device_zone_count=detected_device_zone_count,
    )
    return resolve_calibration_mapping_with_context(config=config, context=context)


def resolve_calibration_mapping_with_context(
    *,
    config: AppConfig,
    context: CalibrationResolverContext,
) -> CalibrationMappingSnapshot:
    calibration = config.effective_calibration()
    configured_device_zone_count = int(getattr(calibration, "device_zone_count", 0))
    device_zone_count = max(1, int(context.effective_device_zone_count))
    if configured_device_zone_count > 0:
        device_zone_count = configured_device_zone_count
    elif context.detected_device_zone_count:
        device_zone_count = max(1, int(context.detected_device_zone_count))
    return resolve_calibration_mapping(
        zone_count=int(context.source_zone_count),
        device_zone_count=device_zone_count,
        zone_offset=int(getattr(calibration, "zone_offset", 0)),
        reverse_zones=bool(getattr(calibration, "reverse_zones", False)),
        manual_mapping_enabled=bool(getattr(calibration, "manual_mapping_enabled", False)),
        explicit_zone_map=getattr(calibration, "explicit_zone_map", None) or None,
        corner_zone_offsets=(
            getattr(calibration, "corner_zone_offsets", None)
            if bool(getattr(calibration, "corner_offsets_enabled", False))
            else None
        ),
        corner_anchor_top_left=int(getattr(calibration, "corner_anchor_top_left", -1)),
        corner_anchor_top_right=int(getattr(calibration, "corner_anchor_top_right", -1)),
        corner_anchor_bottom_right=int(getattr(calibration, "corner_anchor_bottom_right", -1)),
        corner_anchor_bottom_left=int(getattr(calibration, "corner_anchor_bottom_left", -1)),
        calibration_model=str(getattr(calibration, "calibration_model", "offset_direction")),
    )
