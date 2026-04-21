from __future__ import annotations

from typing import Sequence

from nanoleaf_sync.color.zone_mapper import resolve_device_zone_indices


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
) -> list[int]:
    _ = (corner_anchor_top_left, corner_anchor_top_right, corner_anchor_bottom_right, corner_anchor_bottom_left)
    normalized_device_zone_count = int(device_zone_count)
    if normalized_device_zone_count <= 0:
        return resolve_device_zone_indices(
            max(1, int(zone_count)),
            device_zone_count=1,
            zone_offset=int(zone_offset),
            reverse=bool(reverse_zones),
            explicit_zone_map=list(explicit_zone_map) if explicit_zone_map else None,
            corner_zone_offsets=list(corner_zone_offsets) if corner_zone_offsets else None,
        )

    return resolve_device_zone_indices(
        max(1, int(zone_count)),
        device_zone_count=normalized_device_zone_count,
        zone_offset=int(zone_offset),
        reverse=bool(reverse_zones),
        explicit_zone_map=list(explicit_zone_map) if explicit_zone_map else None,
        corner_zone_offsets=list(corner_zone_offsets) if corner_zone_offsets else None,
    )


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
    show_limit: int = 16,
) -> str:
    anchors_supplied = any(v >= 0 for v in (corner_anchor_top_left, corner_anchor_top_right, corner_anchor_bottom_right, corner_anchor_bottom_left))
    indices = mapping_indices(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=reverse_zones,
        explicit_zone_map=explicit_zone_map,
        corner_zone_offsets=corner_zone_offsets,
    )
    limit = max(1, int(show_limit))
    preview = ", ".join(str(i) for i in indices[:limit])
    suffix = "…" if len(indices) > limit else ""
    model = "explicit map" if explicit_zone_map else "offset + direction"
    notes = "\nNote: legacy corner anchors are ignored; calibration uses only offset + direction." if anchors_supplied else ""
    return (
        f"Calibration model: {model} | source zones: {zone_count} | strip zones: {device_zone_count}\n"
        f"Offset: {int(zone_offset):+d} | Direction: {'counter-clockwise' if reverse_zones else 'clockwise'}{notes}\n"
        f"Device zone order (device→screen): {preview}{suffix}"
    )


def mapping_preview_visual(*, show_limit: int = 12, **kwargs) -> str:
    indices = mapping_indices(**kwargs)
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
