from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from nanoleaf_sync.ui.calibration_flow import coverage_progress_label, derive_corner_anchor_device_indices
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
    inactive_color: RGB = (0, 0, 0),
    brightness: float = 1.0,
) -> list[RGB]:
    total = max(1, int(device_zone_count))
    active = {int(i) % total for i in active_indices}
    scale = max(0.0, min(1.0, float(brightness)))

    def _scale(color: RGB) -> RGB:
        return tuple(max(0, min(255, int(round(c * scale)))) for c in color)

    active_scaled = _scale(active_color)
    inactive_scaled = _scale(inactive_color)
    return [active_scaled if i in active else inactive_scaled for i in range(total)]


def single_zone_step(
    *,
    step: int,
    zone_count: int,
    device_zone_count: int,
    zone_offset: int,
    reverse_zones: bool,
    explicit_zone_map: Sequence[int] | None = None,
    label_prefix: str = "Single-zone test",
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
    source_idx = int(mapping[idx]) if mapping else 0
    return CalibrationStep(
        device_zone_index=idx,
        source_zone_index=source_idx,
        label=(
            f"{label_prefix}: strip zone {idx + 1}/{max(1, total)} active "
            f"(source zone #{source_idx + 1})."
        ),
    )


def coverage_sanity_step(
    *,
    step: int,
    zone_count: int,
    device_zone_count: int,
    zone_offset: int,
    reverse_zones: bool,
    explicit_zone_map: Sequence[int] | None = None,
) -> CalibrationStep:
    single = single_zone_step(
        step=step,
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=reverse_zones,
        explicit_zone_map=explicit_zone_map,
        label_prefix="Coverage sanity",
    )
    return CalibrationStep(
        device_zone_index=single.device_zone_index,
        source_zone_index=single.source_zone_index,
        label=coverage_progress_label(
            step=single.device_zone_index,
            device_zone_count=device_zone_count,
            source_zone_index=single.source_zone_index,
        ),
    )


def corner_anchor_steps(
    *,
    zone_count: int,
    device_zone_count: int,
    zone_offset: int,
    reverse_zones: bool,
    explicit_zone_map: Sequence[int] | None = None,
) -> list[CalibrationStep]:
    total = max(1, int(device_zone_count))
    if total == 1:
        return [CalibrationStep(0, 0, "Corner anchor: single-zone strip")]

    corner_names = ["top-left", "top-right", "bottom-right", "bottom-left"]
    mapping = mapping_indices(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=reverse_zones,
        explicit_zone_map=explicit_zone_map,
    )
    anchors = derive_corner_anchor_device_indices(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=reverse_zones,
        explicit_zone_map=explicit_zone_map,
    )
    steps: list[CalibrationStep] = []
    for name, device_idx in zip(corner_names, anchors):
        source_idx = int(mapping[device_idx]) if mapping else 0
        steps.append(
            CalibrationStep(
                device_zone_index=int(device_idx),
                source_zone_index=source_idx,
                label=(
                    f"Corner anchor {name}: light strip zone #{int(device_idx) + 1} "
                    f"(mapped source zone #{source_idx + 1})."
                ),
            )
        )
    return steps
