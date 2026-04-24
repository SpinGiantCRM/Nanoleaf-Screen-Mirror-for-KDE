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
    warning_codes: tuple[str, ...]
    calibration_model: str
    strategy: str
    fallback_strategy: str | None = None

    @property
    def anchor_validation_ok(self) -> bool:
        return not self.validation_warnings

    @property
    def anchor_validation_errors(self) -> tuple[str, ...]:
        # Backwards-compatible alias for older call-sites/tests.
        return self.validation_warnings

    @property
    def invalid_corner_anchor_fallback_active(self) -> bool:
        return self.calibration_model == "corner_anchored" and bool(self.warning_codes)


def _corner_anchor_warning_codes(
    *,
    anchors: dict[str, int | None],
    device_zone_count: int,
) -> tuple[str, ...]:
    total = max(0, int(device_zone_count))
    codes: list[str] = []
    assigned_values = [int(value) for value in anchors.values() if value is not None]
    if any(value is None for value in anchors.values()):
        codes.append("CORNER_ANCHOR_MISSING")
    if len(set(assigned_values)) != len(assigned_values):
        codes.append("CORNER_ANCHOR_DUPLICATE")
    if any(value < 0 or value >= total for value in assigned_values):
        codes.append("CORNER_ANCHOR_OUT_OF_RANGE")
    if total < 4:
        codes.append("DEVICE_ZONE_COUNT_TOO_LOW")
    return tuple(codes)


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
    reverse_zones: bool,
    manual_mapping_enabled: bool,
    explicit_zone_map: Sequence[int] | None = None,
    corner_anchor_top_left: int = -1,
    corner_anchor_top_right: int = -1,
    corner_anchor_bottom_right: int = -1,
    corner_anchor_bottom_left: int = -1,
    calibration_model: str = "corner_anchored",
    source_side_counts: tuple[int, int, int, int] | None = None,
) -> CalibrationMappingSnapshot:
    normalized_model = str(calibration_model or "corner_anchored").strip().lower()
    if normalized_model not in {"corner_anchored"}:
        normalized_model = "corner_anchored"
    anchors = {
        "top_left": _normalize_anchor(corner_anchor_top_left),
        "top_right": _normalize_anchor(corner_anchor_top_right),
        "bottom_right": _normalize_anchor(corner_anchor_bottom_right),
        "bottom_left": _normalize_anchor(corner_anchor_bottom_left),
    }

    validation_warnings: tuple[str, ...] = ()
    warning_codes: tuple[str, ...] = ()
    strategy = "corner_anchored"
    fallback_strategy: str | None = None
    direction = "clockwise"

    normalized_device_zone_count = int(device_zone_count)
    if normalized_device_zone_count <= 0:
        normalized_device_zone_count = 1

    def _direct_mapping() -> list[int]:
        return resolve_device_zone_indices(
            max(1, int(zone_count)),
            device_zone_count=normalized_device_zone_count,
            reverse=bool(reverse_zones),
            manual_mapping_enabled=bool(manual_mapping_enabled),
            explicit_zone_map=list(explicit_zone_map) if explicit_zone_map else None,
        )

    anchor_validation = validate_corner_anchors(anchors=anchors, device_zone_count=device_zone_count)
    if anchor_validation.valid:
        effective_anchors = anchors
    else:
        validation_warnings = tuple(anchor_validation.errors)
        warning_codes = _corner_anchor_warning_codes(
            anchors=anchors,
            device_zone_count=device_zone_count,
        )
        mapping = _direct_mapping()
        return CalibrationMappingSnapshot(
            device_to_source_indices=mapping,
            mode=strategy,
            direction=direction,
            validation_warnings=validation_warnings,
            warning_codes=warning_codes,
            strategy=strategy,
            fallback_strategy="deterministic_anchor_inference",
            calibration_model=normalized_model,
        )

    derive_device_zone_count = max(4, int(device_zone_count))
    anchor_map = derive_anchor_zone_map(
        zone_count=zone_count,
        device_zone_count=derive_device_zone_count,
        anchors=effective_anchors,
        source_side_counts=source_side_counts,
    )
    selected_explicit_map = list(anchor_map.explicit_zone_map)
    target_count = max(1, int(device_zone_count))
    if len(selected_explicit_map) != target_count:
        source_count = len(selected_explicit_map)
        selected_explicit_map = [
            int(selected_explicit_map[(idx * source_count) // target_count]) for idx in range(target_count)
        ]
    direction = anchor_map.direction

    mapping = resolve_device_zone_indices(
        max(1, int(zone_count)),
        device_zone_count=normalized_device_zone_count,
        reverse=bool(reverse_zones),
        manual_mapping_enabled=True,
        explicit_zone_map=selected_explicit_map,
    )
    return CalibrationMappingSnapshot(
        device_to_source_indices=mapping,
        mode=strategy,
        direction=direction,
        validation_warnings=validation_warnings,
        warning_codes=warning_codes,
        strategy=strategy,
        fallback_strategy=fallback_strategy,
        calibration_model=normalized_model,
    )


def resolve_calibration_mapping_from_config(
    *,
    config: AppConfig,
    source_zone_count: int,
    detected_device_zone_count: int | None = None,
    source_side_counts: tuple[int, int, int, int] | None = None,
) -> CalibrationMappingSnapshot:
    calibration = config.effective_calibration()
    configured_device_zone_count = int(getattr(calibration, "device_zone_count", 0))
    if configured_device_zone_count <= 0:
        configured_device_zone_count = int(getattr(config, "device_zone_count", 0) or 0)
    _ = detected_device_zone_count
    context = CalibrationResolverContext(
        source_zone_count=int(source_zone_count),
        effective_device_zone_count=(
            configured_device_zone_count if configured_device_zone_count > 0 else 1
        ),
        detected_device_zone_count=detected_device_zone_count,
    )
    return resolve_calibration_mapping_with_context(
        config=config,
        context=context,
        source_side_counts=source_side_counts,
    )


def resolve_calibration_mapping_with_context(
    *,
    config: AppConfig,
    context: CalibrationResolverContext,
    source_side_counts: tuple[int, int, int, int] | None = None,
) -> CalibrationMappingSnapshot:
    calibration = config.effective_calibration()
    configured_device_zone_count = int(getattr(calibration, "device_zone_count", 0))
    if configured_device_zone_count <= 0:
        configured_device_zone_count = int(getattr(config, "device_zone_count", 0) or 0)
    device_zone_count = max(1, int(context.effective_device_zone_count))
    if configured_device_zone_count > 0:
        device_zone_count = configured_device_zone_count
    return resolve_calibration_mapping(
        zone_count=int(context.source_zone_count),
        device_zone_count=device_zone_count,
        reverse_zones=bool(getattr(calibration, "reverse_zones", False)),
        manual_mapping_enabled=bool(getattr(calibration, "manual_mapping_enabled", False)),
        explicit_zone_map=getattr(calibration, "explicit_zone_map", None) or None,
        corner_anchor_top_left=int(getattr(calibration, "corner_anchor_top_left", -1)),
        corner_anchor_top_right=int(getattr(calibration, "corner_anchor_top_right", -1)),
        corner_anchor_bottom_right=int(getattr(calibration, "corner_anchor_bottom_right", -1)),
        corner_anchor_bottom_left=int(getattr(calibration, "corner_anchor_bottom_left", -1)),
        calibration_model="corner_anchored",
        source_side_counts=source_side_counts,
    )
