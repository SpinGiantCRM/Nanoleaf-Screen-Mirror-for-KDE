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
        key="coverage-sanity",
        title="1) Coverage sanity",
        guidance="Walk a single lit segment across all device zones and confirm the whole strip responds.",
    ),
    CalibrationSequenceStep(
        key="start-point",
        title="2) Start-point identification",
        guidance="Identify where strip zone #1 physically starts on your setup.",
    ),
    CalibrationSequenceStep(
        key="direction-walk",
        title="3) Direction walk",
        guidance="Advance one zone at a time and confirm travel direction around the strip.",
    ),
    CalibrationSequenceStep(
        key="corner-anchors",
        title="4) Corner anchors",
        guidance="Verify screen corner anchors using the current mapped strip order.",
    ),
    CalibrationSequenceStep(
        key="fine-offset",
        title="5) Fine offset",
        guidance="Nudge offset until transitions align with your real corner transitions.",
    ),
    CalibrationSequenceStep(
        key="manual-remap",
        title="6) Manual remap",
        guidance="Only for unusual layouts: assign strip zones to source zones manually.",
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
) -> list[int]:
    mapping = mapping_indices(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=reverse_zones,
        explicit_zone_map=explicit_zone_map,
    )
    if not mapping:
        return [0]

    source_total = max(1, int(zone_count))
    targets = [
        0,
        source_total // 4,
        source_total // 2,
        (3 * source_total) // 4,
    ]

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
        pick = next((device for _, device in scored if device not in used), scored[0][1])
        used.add(int(pick))
        chosen.append(int(pick))
    return chosen
