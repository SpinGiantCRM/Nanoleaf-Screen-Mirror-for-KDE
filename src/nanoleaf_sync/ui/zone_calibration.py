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
) -> list[int]:
    return resolve_device_zone_indices(
        max(1, int(zone_count)),
        device_zone_count=max(1, int(device_zone_count)),
        zone_offset=int(zone_offset),
        reverse=bool(reverse_zones),
        explicit_zone_map=list(explicit_zone_map) if explicit_zone_map else None,
    )


def mapping_preview_text(
    *,
    zone_count: int,
    device_zone_count: int,
    zone_offset: int,
    reverse_zones: bool,
    explicit_zone_map: Sequence[int] | None = None,
    show_limit: int = 16,
) -> str:
    indices = mapping_indices(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=reverse_zones,
        explicit_zone_map=explicit_zone_map,
    )
    preview = ", ".join(str(i) for i in indices[: max(1, int(show_limit))])
    suffix = "…" if len(indices) > show_limit else ""
    mode = "manual" if explicit_zone_map else "simple"
    direction = "counter-clockwise" if reverse_zones else "clockwise"
    return (
        f"Calibration mode: {mode} | source zones: {zone_count} | strip zones: {device_zone_count}\n"
        f"Direction: {direction} | start offset: {zone_offset}\n"
        f"Device zone order (device→screen): {preview}{suffix}"
    )


def mapping_preview_visual(
    *,
    zone_count: int,
    device_zone_count: int,
    zone_offset: int,
    reverse_zones: bool,
    explicit_zone_map: Sequence[int] | None = None,
    show_limit: int = 12,
) -> str:
    indices = mapping_indices(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=reverse_zones,
        explicit_zone_map=explicit_zone_map,
    )
    if not indices:
        return "No mapping available."
    chunks = [f"[D{idx}→S{src}]" for idx, src in enumerate(indices[: max(1, int(show_limit))])]
    suffix = " …" if len(indices) > show_limit else ""
    return " ".join(chunks) + suffix


def zone_test_instruction(step: int, total: int) -> str:
    if total <= 0:
        return "No zones available for test mode."
    idx = int(step) % int(total)
    return f"Test mode: highlight physical strip segment #{idx + 1} now."
