from __future__ import annotations

from typing import Sequence

from nanoleaf_sync.color.zone_mapper import resolve_device_zone_indices
from nanoleaf_sync.runtime.anchor_calibration import derive_anchor_zone_map, validate_corner_anchors


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

    anchors = {
        "top_left": corner_anchor_top_left if corner_anchor_top_left >= 0 else None,
        "top_right": corner_anchor_top_right if corner_anchor_top_right >= 0 else None,
        "bottom_right": corner_anchor_bottom_right if corner_anchor_bottom_right >= 0 else None,
        "bottom_left": corner_anchor_bottom_left if corner_anchor_bottom_left >= 0 else None,
    }
    validation = validate_corner_anchors(anchors=anchors, device_zone_count=normalized_device_zone_count)
    if validation.valid:
        return derive_anchor_zone_map(
            zone_count=zone_count,
            device_zone_count=normalized_device_zone_count,
            anchors=anchors,
        ).explicit_zone_map

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
    normalized_device_zone_count = int(device_zone_count)
    anchors = {
        "top_left": corner_anchor_top_left if corner_anchor_top_left >= 0 else None,
        "top_right": corner_anchor_top_right if corner_anchor_top_right >= 0 else None,
        "bottom_right": corner_anchor_bottom_right if corner_anchor_bottom_right >= 0 else None,
        "bottom_left": corner_anchor_bottom_left if corner_anchor_bottom_left >= 0 else None,
    }
    anchor_line = "Corner anchors: incomplete"
    direction = "n/a"
    edges = "n/a"
    if normalized_device_zone_count <= 0:
        anchor_line = "Corner anchors: waiting for device zone count."
    else:
        validation = validate_corner_anchors(anchors=anchors, device_zone_count=normalized_device_zone_count)
        if validation.valid:
            derived = derive_anchor_zone_map(
                zone_count=zone_count,
                device_zone_count=normalized_device_zone_count,
                anchors=anchors,
            )
            direction = derived.direction
            edges = "/".join(str(v) for v in derived.edge_lengths)
            anchor_line = (
                f"Corner anchors (TL/TR/BR/BL): {corner_anchor_top_left}/{corner_anchor_top_right}/{corner_anchor_bottom_right}/{corner_anchor_bottom_left}"
            )
        else:
            anchor_line = f"Corner anchors: {'; '.join(validation.errors)}"

    indices = mapping_indices(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=reverse_zones,
        explicit_zone_map=explicit_zone_map,
        corner_zone_offsets=corner_zone_offsets,
        corner_anchor_top_left=corner_anchor_top_left,
        corner_anchor_top_right=corner_anchor_top_right,
        corner_anchor_bottom_right=corner_anchor_bottom_right,
        corner_anchor_bottom_left=corner_anchor_bottom_left,
    )
    limit = max(1, int(show_limit))
    preview = ", ".join(str(i) for i in indices[:limit])
    suffix = "…" if len(indices) > limit else ""
    return (
        f"Calibration model: corner anchors | source zones: {zone_count} | strip zones: {device_zone_count}\n"
        f"{anchor_line}\n"
        f"Derived direction: {direction} | edge spans: {edges}\n"
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
