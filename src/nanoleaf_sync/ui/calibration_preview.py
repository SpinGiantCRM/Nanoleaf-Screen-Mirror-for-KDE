from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from nanoleaf_sync.ui.calibration_flow import (
    coverage_progress_label,
    derive_corner_anchor_device_indices,
)
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
        red, green, blue = color
        return (
            max(0, min(255, int(round(red * scale)))),
            max(0, min(255, int(round(green * scale)))),
            max(0, min(255, int(round(blue * scale)))),
        )

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
    corner_zone_offsets: Sequence[int] | None = None,
    calibration_model: str = "offset_direction",
    corner_anchor_top_left: int = -1,
    corner_anchor_top_right: int = -1,
    corner_anchor_bottom_right: int = -1,
    corner_anchor_bottom_left: int = -1,
    label_prefix: str = "Single-zone test",
) -> CalibrationStep:
    mapping = mapping_indices(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=reverse_zones,
        explicit_zone_map=explicit_zone_map,
        corner_zone_offsets=corner_zone_offsets,
        calibration_model=calibration_model,
        corner_anchor_top_left=corner_anchor_top_left,
        corner_anchor_top_right=corner_anchor_top_right,
        corner_anchor_bottom_right=corner_anchor_bottom_right,
        corner_anchor_bottom_left=corner_anchor_bottom_left,
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
    corner_zone_offsets: Sequence[int] | None = None,
    calibration_model: str = "offset_direction",
    corner_anchor_top_left: int = -1,
    corner_anchor_top_right: int = -1,
    corner_anchor_bottom_right: int = -1,
    corner_anchor_bottom_left: int = -1,
) -> CalibrationStep:
    single = single_zone_step(
        step=step,
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=reverse_zones,
        explicit_zone_map=explicit_zone_map,
        corner_zone_offsets=corner_zone_offsets,
        calibration_model=calibration_model,
        corner_anchor_top_left=corner_anchor_top_left,
        corner_anchor_top_right=corner_anchor_top_right,
        corner_anchor_bottom_right=corner_anchor_bottom_right,
        corner_anchor_bottom_left=corner_anchor_bottom_left,
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
    corner_zone_offsets: Sequence[int] | None = None,
    start_anchor: int | None = None,
    calibration_model: str = "offset_direction",
    corner_anchor_top_left: int = -1,
    corner_anchor_top_right: int = -1,
    corner_anchor_bottom_right: int = -1,
    corner_anchor_bottom_left: int = -1,
) -> list[CalibrationStep]:
    total = max(1, int(device_zone_count))
    mapping = mapping_indices(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=reverse_zones,
        explicit_zone_map=explicit_zone_map,
        corner_zone_offsets=corner_zone_offsets,
        calibration_model=calibration_model,
        corner_anchor_top_left=corner_anchor_top_left,
        corner_anchor_top_right=corner_anchor_top_right,
        corner_anchor_bottom_right=corner_anchor_bottom_right,
        corner_anchor_bottom_left=corner_anchor_bottom_left,
    )
    if total == 1:
        return [CalibrationStep(0, 0, "Corner marker: single-zone strip")]
    corner_names = ["top-left", "top-right", "bottom-right", "bottom-left"]
    indices = derive_corner_anchor_device_indices(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=reverse_zones,
        explicit_zone_map=explicit_zone_map,
        corner_zone_offsets=corner_zone_offsets,
        start_anchor=start_anchor,
        calibration_model=calibration_model,
    )
    steps: list[CalibrationStep] = []
    for i, device_idx in enumerate(indices):
        source_idx = int(mapping[device_idx]) if mapping else 0
        label_name = corner_names[i] if i < len(corner_names) else f"marker {i + 1}"
        steps.append(
            CalibrationStep(
                device_zone_index=device_idx,
                source_zone_index=source_idx,
                label=f"Corner marker {label_name}: strip zone #{device_idx + 1}.",
            )
        )
    return steps
