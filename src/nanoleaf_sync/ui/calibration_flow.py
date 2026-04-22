from __future__ import annotations

from dataclasses import dataclass

from nanoleaf_sync.ui.zone_calibration import mapping_indices


@dataclass(frozen=True)
class CalibrationSequenceStep:
    step_id: str
    title: str
    mode: str
    prerequisites: tuple[str, ...]
    pass_criteria: str
    fail_criteria: str
    hints: tuple[str, ...]
    remediation: str | None = None


CALIBRATION_SEQUENCE: tuple[CalibrationSequenceStep, ...] = (
    CalibrationSequenceStep(
        step_id="start-point-detection",
        title="1) Start-point detection",
        mode="start-point identification",
        prerequisites=(),
        pass_criteria="Active test zone is confirmed at the physical top-left start position.",
        fail_criteria="User cannot confidently identify the first zone near top-left.",
        hints=(
            "Use Next/Previous test-zone walk to track LED order.",
            "Reduce room lighting to improve visibility of the active zone.",
        ),
        remediation="Adjust physical strip placement or lower ambient brightness, then retry the walk.",
    ),
    CalibrationSequenceStep(
        step_id="direction-verification",
        title="2) Direction verification",
        mode="direction walk",
        prerequisites=("start-point-detection",),
        pass_criteria="Zone walk moves around the display perimeter in the expected direction.",
        fail_criteria="Zone walk appears mirrored/reversed around screen edges.",
        hints=(
            "Toggle reverse orientation when movement appears backwards.",
            "Confirm at least one full cycle around the strip.",
        ),
        remediation="Toggle reverse strip orientation and repeat a full perimeter walk.",
    ),
    CalibrationSequenceStep(
        step_id="corner-assignment",
        title="3) Corner assignment",
        mode="corner+offset alignment",
        prerequisites=("direction-verification",),
        pass_criteria="Top-left, top-right, bottom-right, and bottom-left corner anchors are coherent.",
        fail_criteria="Corner anchors are missing, duplicated, or invalid for strip size.",
        hints=(
            "Assign corners while the intended zone is active.",
            "If anchor model is disabled, verify equivalent corner positions in the walk.",
        ),
        remediation="Re-assign corners and re-run anchor validation until all corners pass.",
    ),
    CalibrationSequenceStep(
        step_id="edge-refinement",
        title="4) Edge refinement / fine alignment",
        mode="fine offset",
        prerequisites=("corner-assignment",),
        pass_criteria="Edge transitions look smooth without obvious zone drift or jump.",
        fail_criteria="Edge colors appear shifted or transitions skip expected zones.",
        hints=(
            "Use small offset adjustments and check multiple edges.",
            "Validate both horizontal and vertical spans before continuing.",
        ),
        remediation="Apply fine offset adjustments and rerun edge checks until drift is eliminated.",
    ),
    CalibrationSequenceStep(
        step_id="validation-replay",
        title="5) End-to-end validation replay",
        mode="coverage sanity",
        prerequisites=("edge-refinement",),
        pass_criteria="Full replay covers all physical zones with expected source mapping.",
        fail_criteria="Any zone appears unmapped, duplicated unexpectedly, or misplaced.",
        hints=(
            "Run at least one complete cycle through all strip zones.",
            "Watch for dead spots where no active zone appears.",
        ),
        remediation="Return to the failing phase and correct mapping, then replay validation.",
    ),
)


def calibration_sequence_text() -> str:
    lines: list[str] = []
    for step in CALIBRATION_SEQUENCE:
        lines.append(f"{step.title}: {step.pass_criteria}")
        lines.extend(f"  - Hint: {hint}" for hint in step.hints)
        if step.remediation:
            lines.append(f"  - Remediation: {step.remediation}")
    return "\n".join(lines)


def calibration_step_by_id(step_id: str) -> CalibrationSequenceStep | None:
    for step in CALIBRATION_SEQUENCE:
        if step.step_id == step_id:
            return step
    return None


def coverage_progress_label(*, step: int, device_zone_count: int, source_zone_index: int) -> str:
    total = max(1, int(device_zone_count))
    idx = int(step) % total
    return f"Coverage sanity: zone {idx + 1}/{total} active (maps to source zone #{int(source_zone_index) + 1})."



def derive_corner_anchor_device_indices(
    *,
    zone_count: int,
    device_zone_count: int,
    zone_offset: int,
    reverse_zones: bool,
    explicit_zone_map=None,
    corner_zone_offsets=None,
    start_anchor: int | None = None,
    calibration_model: str = "offset_direction",
) -> list[int]:
    total = max(1, int(device_zone_count))
    if total == 1:
        return [0]

    mapping = mapping_indices(
        zone_count=zone_count,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=reverse_zones,
        explicit_zone_map=explicit_zone_map,
        corner_zone_offsets=corner_zone_offsets,
        calibration_model=calibration_model,
    )
    source_total = max(1, int(zone_count))
    corner_targets = [0, source_total // 4, source_total // 2, (3 * source_total) // 4]
    def _ring_distance(a: int, b: int, length: int) -> int:
        diff = abs(int(a) - int(b)) % length
        return min(diff, length - diff)

    anchored_device_idx = (int(start_anchor) % total) if start_anchor is not None else None
    used: set[int] = set()
    ordered: list[int] = []
    for corner_idx in range(4):
        if corner_idx == 0 and anchored_device_idx is not None:
            ordered.append(anchored_device_idx)
            used.add(anchored_device_idx)
            continue
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
