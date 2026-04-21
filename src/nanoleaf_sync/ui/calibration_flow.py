from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from nanoleaf_sync.ui.zone_calibration import mapping_indices


@dataclass(frozen=True)
class CalibrationSequenceStep:
    key: str
    title: str
    guidance: str


CALIBRATION_SEQUENCE: tuple[CalibrationSequenceStep, ...] = (
    CalibrationSequenceStep(
        key="corner-anchor-pass",
        title="1) Corner anchor pass",
        guidance="Walk the active zone to each physical corner and assign Top-left/Top-right/Bottom-right/Bottom-left.",
    ),
    CalibrationSequenceStep(
        key="offset-trim",
        title="2) Offset trim",
        guidance="Nudge global zone offset until corner transitions line up with real screen transitions.",
    ),
    CalibrationSequenceStep(
        key="verify-repeatability",
        title="3) Verify repeatability",
        guidance="Re-send test pattern after each small offset change and verify movement is predictable.",
    ),
)


def calibration_sequence_text() -> str:
    return "\n".join(f"{step.title}: {step.guidance}" for step in CALIBRATION_SEQUENCE)


def coverage_progress_label(*, step: int, device_zone_count: int, source_zone_index: int) -> str:
    total = max(1, int(device_zone_count))
    idx = int(step) % total
    return (
        f"Coverage sanity: zone {idx + 1}/{total} active "
        f"(maps to source zone #{int(source_zone_index) + 1})."
    )


def derive_corner_anchor_device_indices(
    *,
    zone_count: int,
    device_zone_count: int,
    zone_offset: int,
    reverse_zones: bool,
    explicit_zone_map: Sequence[int] | None = None,
    corner_zone_offsets: Sequence[int] | None = None,
    start_anchor: int | None = None,
) -> list[int]:
    mapping = mapping_indices(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=reverse_zones,
        explicit_zone_map=explicit_zone_map,
        corner_zone_offsets=corner_zone_offsets,
    )
    if not mapping:
        return [0]


    if start_anchor is not None and len(mapping) > 0:
        total = len(mapping)
        start = int(start_anchor) % total
        if total == 1:
            return [0]
        quarter = max(1, total // 4)
        ordered = [
            start,
            (start + quarter) % total,
            (start + 2 * quarter) % total,
            (start + 3 * quarter) % total,
        ]
        unique: list[int] = []
        for idx in ordered:
            if idx not in unique:
                unique.append(idx)
        return unique[: min(4, total)]
    source_total = max(1, int(zone_count))
    targets = [
        0,
        source_total // 4,
        source_total // 2,
        (3 * source_total) // 4,
    ][: min(4, len(mapping))]

    def _ring_distance(a: int, b: int, length: int) -> int:
        d = abs(a - b) % length
        return min(d, length - d)

    chosen: list[int] = []
    used: set[int] = set()
    for target in targets:
        scored = sorted(
            (
                (_ring_distance(int(source_idx), int(target), source_total), device_idx)
                for device_idx, source_idx in enumerate(mapping)
            ),
            key=lambda item: (item[0], item[1]),
        )
        pick = next((device for _, device in scored if device not in used), None)
        if pick is None:
            break
        used.add(int(pick))
        chosen.append(int(pick))
    return chosen
