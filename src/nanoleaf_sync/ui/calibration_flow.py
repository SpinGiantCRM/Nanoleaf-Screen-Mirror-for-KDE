from __future__ import annotations

from dataclasses import dataclass

from nanoleaf_sync.ui.zone_calibration import mapping_indices


@dataclass(frozen=True)
class CalibrationSequenceStep:
    key: str
    title: str
    guidance: str


CALIBRATION_SEQUENCE: tuple[CalibrationSequenceStep, ...] = (
    CalibrationSequenceStep(
        key="find-top-left",
        title="1) Find top-left strip zone",
        guidance="Walk one strip zone at a time and note which zone is physically at your monitor top-left.",
    ),
    CalibrationSequenceStep(
        key="set-offset",
        title="2) Set offset",
        guidance="Set global offset to the zone number at top-left.",
    ),
    CalibrationSequenceStep(
        key="set-direction",
        title="3) Set direction",
        guidance="Toggle reverse if the active zone walks the wrong direction around the screen.",
    ),
)


def calibration_sequence_text() -> str:
    return "\n".join(f"{step.title}: {step.guidance}" for step in CALIBRATION_SEQUENCE)


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
    )
    source_total = max(1, int(zone_count))
    corner_targets = [0, source_total // 4, source_total // 2, (3 * source_total) // 4]
    start = int(start_anchor) % len(corner_targets) if start_anchor is not None else 0

    def _ring_distance(a: int, b: int, length: int) -> int:
        diff = abs(int(a) - int(b)) % length
        return min(diff, length - diff)

    ordered: list[int] = []
    for corner_idx in range(4):
        target = corner_targets[(start + corner_idx) % len(corner_targets)]
        best = min(
            range(total),
            key=lambda device_idx: (
                _ring_distance(int(mapping[device_idx]), target, source_total),
                device_idx,
            ),
        )
        ordered.append(best)

    out: list[int] = []
    for idx in ordered:
        if idx not in out:
            out.append(idx)
    return out[: min(4, total)]
