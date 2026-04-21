from __future__ import annotations

from dataclasses import dataclass


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
    _ = (zone_count, zone_offset, reverse_zones, explicit_zone_map, corner_zone_offsets)
    total = max(1, int(device_zone_count))
    if total == 1:
        return [0]
    start = int(start_anchor) % total if start_anchor is not None else 0
    quarter = max(1, total // 4)
    ordered = [start, (start + quarter) % total, (start + 2 * quarter) % total, (start + 3 * quarter) % total]
    out: list[int] = []
    for idx in ordered:
        if idx not in out:
            out.append(idx)
    return out[: min(4, total)]
