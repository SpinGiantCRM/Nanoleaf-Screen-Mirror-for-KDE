from __future__ import annotations

from typing import Sequence

from nanoleaf_sync.runtime.calibration_resolver import (
    CalibrationMappingSnapshot,
    resolve_calibration_mapping,
)


def mapping_indices(
    *,
    zone_count: int,
    device_zone_count: int,
    zone_offset: int,
    reverse_zones: bool,
    explicit_zone_map: Sequence[int] | None = None,
    corner_zone_offsets: Sequence[int] | None = None,
    corner_anchor_top_left: int = -1,
    corner_anchor_top_right: int = -1,
    corner_anchor_bottom_right: int = -1,
    corner_anchor_bottom_left: int = -1,
    calibration_model: str = "offset_direction",
) -> list[int]:
    snapshot = resolve_calibration_mapping(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=reverse_zones,
        manual_mapping_enabled=bool(explicit_zone_map),
        explicit_zone_map=explicit_zone_map,
        corner_zone_offsets=corner_zone_offsets,
        corner_anchor_top_left=corner_anchor_top_left,
        corner_anchor_top_right=corner_anchor_top_right,
        corner_anchor_bottom_right=corner_anchor_bottom_right,
        corner_anchor_bottom_left=corner_anchor_bottom_left,
        calibration_model=calibration_model,
    )
    return snapshot.device_to_source_indices


def mapping_preview_text(
    *,
    zone_count: int,
    device_zone_count: int,
    zone_offset: int,
    reverse_zones: bool,
    explicit_zone_map: Sequence[int] | None = None,
    corner_zone_offsets: Sequence[int] | None = None,
    corner_anchor_top_left: int = -1,
    corner_anchor_top_right: int = -1,
    corner_anchor_bottom_right: int = -1,
    corner_anchor_bottom_left: int = -1,
    calibration_model: str = "offset_direction",
    resolved_mapping: CalibrationMappingSnapshot | None = None,
    show_limit: int = 16,
) -> str:
    snapshot = resolved_mapping or resolve_calibration_mapping(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=reverse_zones,
        manual_mapping_enabled=bool(explicit_zone_map),
        explicit_zone_map=explicit_zone_map,
        corner_zone_offsets=corner_zone_offsets,
        corner_anchor_top_left=corner_anchor_top_left,
        corner_anchor_top_right=corner_anchor_top_right,
        corner_anchor_bottom_right=corner_anchor_bottom_right,
        corner_anchor_bottom_left=corner_anchor_bottom_left,
        calibration_model=calibration_model,
    )
    indices = snapshot.device_to_source_indices
    limit = max(1, int(show_limit))
    preview = ", ".join(str(i) for i in indices[:limit])
    suffix = "…" if len(indices) > limit else ""
    if snapshot.calibration_model == "corner_anchored":
        model = "corner anchored"
        notes = ""
        if snapshot.anchor_validation_errors:
            notes = f"\nCorner anchor validation: {'; '.join(snapshot.anchor_validation_errors)}"
    else:
        model = "explicit map" if explicit_zone_map else "offset + direction"
        notes = ""
    return (
        f"Calibration model: {model} | source zones: {zone_count} | strip zones: {device_zone_count}\n"
        f"Offset: {int(zone_offset):+d} | Direction: {'counter-clockwise' if reverse_zones else 'clockwise'}{notes}\n"
        f"Device zone order (device→screen): {preview}{suffix}"
    )


def mapping_preview_visual(*, show_limit: int = 12, resolved_mapping: CalibrationMappingSnapshot | None = None, **kwargs) -> str:
    indices = resolved_mapping.device_to_source_indices if resolved_mapping else mapping_indices(**kwargs)
    if not indices:
        return "No mapping available."
    limit = max(1, int(show_limit))
    chunks = [f"[D{idx}→S{src}]" for idx, src in enumerate(indices[:limit])]
    return " ".join(chunks) + (" …" if len(indices) > limit else "")


def zone_test_instruction(step: int, total: int) -> str:
    if total <= 0:
        return "No zones available for test mode."
    idx = int(step) % int(total)
    return f"Test mode: highlight physical strip segment #{idx + 1} now."
