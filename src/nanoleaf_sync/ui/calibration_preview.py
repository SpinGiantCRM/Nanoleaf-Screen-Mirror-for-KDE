from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from nanoleaf_sync.ui.zone_calibration import mapping_indices


RGB = tuple[int, int, int]


@dataclass(frozen=True)
class CalibrationStep:
    device_zone_index: int
    source_zone_index: int
    label: str


def calibration_test_frame(
    *,
    device_zone_count: int,
    active_indices: Sequence[int],
    active_color: RGB = (255, 170, 32),
) -> list[RGB]:
    total = max(1, int(device_zone_count))
    active = {int(i) % total for i in active_indices}
    return [active_color if i in active else (0, 0, 0) for i in range(total)]


def single_zone_step(
    *,
    step: int,
    zone_count: int,
    device_zone_count: int,
    zone_offset: int,
    reverse_zones: bool,
    explicit_zone_map: Sequence[int] | None = None,
) -> CalibrationStep:
    mapping = mapping_indices(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=reverse_zones,
        explicit_zone_map=explicit_zone_map,
    )
    total = len(mapping)
    idx = int(step) % max(1, total)
    return CalibrationStep(
        device_zone_index=idx,
        source_zone_index=int(mapping[idx]) if mapping else 0,
        label=f"Single-zone test: strip #{idx + 1} should be the only lit segment.",
    )


def corner_anchor_steps(*, device_zone_count: int) -> list[CalibrationStep]:
    total = max(1, int(device_zone_count))
    if total == 1:
        return [CalibrationStep(0, 0, "Corner anchor: single-zone strip")]

    # Simple, explicit anchors around the strip path.
    anchor_indices = [
        0,
        total // 4,
        total // 2,
        (3 * total) // 4,
    ]
    labels = ["top-left", "top-right", "bottom-right", "bottom-left"]
    return [
        CalibrationStep(
            device_zone_index=i % total,
            source_zone_index=i % total,
            label=f"Corner anchor: {label}",
        )
        for i, label in zip(anchor_indices, labels)
    ]
