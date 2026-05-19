from __future__ import annotations

from nanoleaf_sync.ui.zone_calibration import mapping_indices


def coverage_progress_label(*, step: int, device_zone_count: int, source_zone_index: int) -> str:
    total = max(1, int(device_zone_count))
    idx = int(step) % total
    return f"Coverage sanity: zone {idx + 1}/{total} active (maps to source zone #{int(source_zone_index) + 1})."


def derive_corner_anchor_device_indices(
    *,
    zone_count: int,
    device_zone_count: int,
    reverse_zones: bool,
    calibration_model: str = "corner_anchored",
    source_side_counts: tuple[int, int, int, int] | None = None,
) -> list[int]:
    total = max(1, int(device_zone_count))
    if total == 1:
        return [0]

    mapping = mapping_indices(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        reverse_zones=reverse_zones,
        calibration_model=calibration_model,
    )
    if len(mapping) != total:
        mapping = list(range(total))
        if reverse_zones:
            mapping = list(reversed(mapping))
    source_total = max(1, int(zone_count))
    if source_side_counts is not None and sum(source_side_counts) == source_total:
        top, right, bottom, _left = source_side_counts
        corner_targets = [0, top, top + right, top + right + bottom]
    else:
        corner_targets = [0, source_total // 4, source_total // 2, (3 * source_total) // 4]

    def _ring_distance(a: int, b: int, length: int) -> int:
        diff = abs(int(a) - int(b)) % length
        return min(diff, length - diff)

    used: set[int] = set()
    ordered: list[int] = []
    for corner_idx in range(4):
        target = corner_targets[corner_idx % len(corner_targets)]
        candidates = [idx for idx in range(total) if idx not in used]
        if not candidates:
            break
        best = min(
            candidates,
            key=lambda device_idx: (
                _ring_distance(int(mapping[device_idx]), target, source_total),
                device_idx,
            ),
        )
        ordered.append(best)
        used.add(best)
    return ordered[: min(4, total)]
