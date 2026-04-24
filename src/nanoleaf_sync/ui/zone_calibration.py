from __future__ import annotations

from collections import Counter
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.calibration_resolver import (
    CalibrationMappingSnapshot,
    resolve_calibration_mapping,
    resolve_calibration_mapping_from_config,
)

_CORNER_FIELDS: tuple[tuple[str, str], ...] = (
    ("top_left", "TL"),
    ("top_right", "TR"),
    ("bottom_right", "BR"),
    ("bottom_left", "BL"),
)


def corner_anchor_validation_summary(
    *,
    device_zone_count: int,
    corner_anchor_top_left: int = -1,
    corner_anchor_top_right: int = -1,
    corner_anchor_bottom_right: int = -1,
    corner_anchor_bottom_left: int = -1,
) -> str:
    values = {
        "top_left": int(corner_anchor_top_left),
        "top_right": int(corner_anchor_top_right),
        "bottom_right": int(corner_anchor_bottom_right),
        "bottom_left": int(corner_anchor_bottom_left),
    }
    valid_min = 0
    valid_max = int(device_zone_count) - 1
    missing = [abbr for name, abbr in _CORNER_FIELDS if values[name] < 0]
    assigned = {name: idx for name, idx in values.items() if idx >= 0}
    duplicate_groups = [
        f"{idx} ({'/'.join(abbr for name, abbr in _CORNER_FIELDS if assigned.get(name) == idx)})"
        for idx, count in sorted(Counter(assigned.values()).items())
        if count > 1
    ]
    out_of_range = [
        f"{abbr}={idx}"
        for name, abbr in _CORNER_FIELDS
        for idx in [assigned.get(name)]
        if idx is not None and (idx < valid_min or idx > valid_max)
    ]
    return (
        "Anchor validation summary: "
        f"missing corners: {', '.join(missing) if missing else 'none'} | "
        f"duplicate zone assignments: {', '.join(duplicate_groups) if duplicate_groups else 'none'} | "
        f"out-of-range assignments: {', '.join(out_of_range) if out_of_range else 'none'}"
    )


def mapping_indices(
    *,
    zone_count: int,
    device_zone_count: int,
    reverse_zones: bool,
    corner_anchor_top_left: int = -1,
    corner_anchor_top_right: int = -1,
    corner_anchor_bottom_right: int = -1,
    corner_anchor_bottom_left: int = -1,
    calibration_model: str = "corner_anchored",
) -> list[int]:
    snapshot = resolve_calibration_mapping(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        reverse_zones=reverse_zones,
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
    reverse_zones: bool,
    corner_anchor_top_left: int = -1,
    corner_anchor_top_right: int = -1,
    corner_anchor_bottom_right: int = -1,
    corner_anchor_bottom_left: int = -1,
    calibration_model: str = "corner_anchored",
    resolved_mapping: CalibrationMappingSnapshot | None = None,
    show_limit: int = 16,
) -> str:
    snapshot = resolved_mapping or resolve_calibration_mapping(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        reverse_zones=reverse_zones,
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
    model = "corner calibration"
    detail_line = (
        f"Anchors (TL/TR/BR/BL): {corner_anchor_top_left}, "
        f"{corner_anchor_top_right}, "
        f"{corner_anchor_bottom_right}, "
        f"{corner_anchor_bottom_left}"
    )
    summary = corner_anchor_validation_summary(
        device_zone_count=device_zone_count,
        corner_anchor_top_left=corner_anchor_top_left,
        corner_anchor_top_right=corner_anchor_top_right,
        corner_anchor_bottom_right=corner_anchor_bottom_right,
        corner_anchor_bottom_left=corner_anchor_bottom_left,
    )
    notes = ""
    if snapshot.anchor_validation_errors:
        notes = (
            "\nCalibration invalid: assign four unique in-range corner anchors."
            f"\n{summary}"
            f"\nCorner anchor validation: {'; '.join(snapshot.anchor_validation_errors)}"
        )
    else:
        notes = (
            "\nCorner anchors drive mapping for this calibration mode."
            f"\n{summary}"
        )
    return (
        f"Calibration model: {model} | source zones: {zone_count} | strip zones: {device_zone_count}\n"
        f"{detail_line}{notes}\n"
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


def mapping_snapshot_from_config(
    *,
    config: AppConfig,
    source_zone_count: int,
    detected_device_zone_count: int | None = None,
) -> CalibrationMappingSnapshot:
    return resolve_calibration_mapping_from_config(
        config=config,
        source_zone_count=source_zone_count,
        detected_device_zone_count=detected_device_zone_count,
    )
