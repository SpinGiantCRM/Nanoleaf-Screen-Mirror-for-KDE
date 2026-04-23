from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from nanoleaf_sync.runtime.anchor_calibration import validate_corner_anchors
from nanoleaf_sync.ui.zone_calibration import mapping_indices

if TYPE_CHECKING:
    from nanoleaf_sync.ui.calibration_state import CalibrationState


ValidationFn = Callable[["CalibrationState", "CalibrationPhaseDefinition"], tuple[bool, str]]


@dataclass(frozen=True)
class CalibrationPhaseDefinition:
    step_id: str
    title: str
    mode: str
    prerequisites: tuple[str, ...]
    required_actions: tuple[str, ...]
    validation_fn: ValidationFn
    remediation_hints: tuple[str, ...]
    pass_criteria: str
    fail_criteria: str


def _validate_step_marked_passed(state: "CalibrationState", phase: CalibrationPhaseDefinition) -> tuple[bool, str]:
    progress = state.calibration_step_state(phase.step_id)
    if progress.passed:
        return True, "Phase has been marked as passed."
    return False, "Phase is not marked as passed yet."


def _validate_corner_assignment(state: "CalibrationState", phase: CalibrationPhaseDefinition) -> tuple[bool, str]:
    progress = state.calibration_step_state(phase.step_id)
    anchors = {
        "top_left": state.corner_anchor_top_left if state.corner_anchor_top_left >= 0 else None,
        "top_right": state.corner_anchor_top_right if state.corner_anchor_top_right >= 0 else None,
        "bottom_right": state.corner_anchor_bottom_right if state.corner_anchor_bottom_right >= 0 else None,
        "bottom_left": state.corner_anchor_bottom_left if state.corner_anchor_bottom_left >= 0 else None,
    }
    result = validate_corner_anchors(anchors=anchors, device_zone_count=state.effective_device_zone_count())
    if not result.valid:
        return False, "Corner anchors invalid: " + "; ".join(result.errors)
    if not progress.passed:
        return False, "Corner anchors are valid, but phase is not marked as passed."
    return True, "Corner anchors validated and phase marked passed."


def _validate_final_replay(state: "CalibrationState", phase: CalibrationPhaseDefinition) -> tuple[bool, str]:
    progress = state.calibration_step_state(phase.step_id)
    report = state.validation_report()
    if not progress.passed:
        return False, "Validation replay phase is not marked as passed."
    if report.confidence_score < 1.0:
        return False, f"Validation confidence too low ({report.confidence_score:.2f})."
    return True, "Replay phase passed with full validation confidence."


CALIBRATION_SEQUENCE: tuple[CalibrationPhaseDefinition, ...] = (
    CalibrationPhaseDefinition(
        step_id="start-point-detection",
        title="1) Start-point detection",
        mode="start-point identification",
        prerequisites=(),
        required_actions=(
            "Run zone stepping until the first physical strip zone is identified near top-left.",
            "Mark phase passed only after visual confirmation.",
        ),
        validation_fn=_validate_step_marked_passed,
        remediation_hints=(
            "Use Next/Previous test-zone walk to track LED order.",
            "Reduce room lighting to improve visibility of the active zone.",
        ),
        pass_criteria="Active test zone is confirmed at the physical top-left start position.",
        fail_criteria="User cannot confidently identify the first zone near top-left.",
    ),
    CalibrationPhaseDefinition(
        step_id="direction-verification",
        title="2) Direction verification",
        mode="direction walk",
        prerequisites=("start-point-detection",),
        required_actions=(
            "Walk one full cycle around the strip.",
            "Confirm reverse orientation and offset align with physical direction.",
        ),
        validation_fn=_validate_step_marked_passed,
        remediation_hints=(
            "Toggle reverse orientation when movement appears backwards.",
            "Confirm at least one full cycle around the strip.",
        ),
        pass_criteria="Zone walk moves around the display perimeter in the expected direction.",
        fail_criteria="Zone walk appears mirrored/reversed around screen edges.",
    ),
    CalibrationPhaseDefinition(
        step_id="corner-assignment",
        title="3) Corner assignment",
        mode="corner+offset alignment",
        prerequisites=("direction-verification",),
        required_actions=(
            "Assign TL/TR/BR/BL corner anchors.",
            "Verify all anchors are unique and within strip range.",
        ),
        validation_fn=_validate_corner_assignment,
        remediation_hints=(
            "Assign corners while the intended zone is active.",
            "Verify equivalent corner positions in the walk.",
        ),
        pass_criteria="Top-left, top-right, bottom-right, and bottom-left corner anchors are coherent.",
        fail_criteria="Corner anchors are missing, duplicated, or invalid for strip size.",
    ),
    CalibrationPhaseDefinition(
        step_id="edge-refinement",
        title="4) Edge refinement / fine alignment",
        mode="fine offset",
        prerequisites=("corner-assignment",),
        required_actions=(
            "Tune offset until edge transitions are smooth.",
            "Check both horizontal and vertical edges.",
        ),
        validation_fn=_validate_step_marked_passed,
        remediation_hints=(
            "Use small offset adjustments and check multiple edges.",
            "Validate both horizontal and vertical spans before continuing.",
        ),
        pass_criteria="Edge transitions look smooth without obvious zone drift or jump.",
        fail_criteria="Edge colors appear shifted or transitions skip expected zones.",
    ),
    CalibrationPhaseDefinition(
        step_id="validation-replay",
        title="5) End-to-end validation replay",
        mode="coverage sanity",
        prerequisites=("edge-refinement",),
        required_actions=(
            "Run a complete cycle through all strip zones.",
            "Confirm no dead spots, duplicates, or sentinel mismatch.",
        ),
        validation_fn=_validate_final_replay,
        remediation_hints=(
            "Run at least one complete cycle through all strip zones.",
            "Watch for dead spots where no active zone appears.",
        ),
        pass_criteria="Full replay covers all physical zones with expected source mapping.",
        fail_criteria="Any zone appears unmapped, duplicated unexpectedly, or misplaced.",
    ),
)


def calibration_sequence_text() -> str:
    lines: list[str] = []
    for step in CALIBRATION_SEQUENCE:
        lines.append(f"{step.title}: {step.pass_criteria}")
        lines.extend(f"  - Required action: {action}" for action in step.required_actions)
        lines.extend(f"  - Hint: {hint}" for hint in step.remediation_hints)
    return "\n".join(lines)


def calibration_step_by_id(step_id: str) -> CalibrationPhaseDefinition | None:
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
    calibration_model: str = "corner_anchored",
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
