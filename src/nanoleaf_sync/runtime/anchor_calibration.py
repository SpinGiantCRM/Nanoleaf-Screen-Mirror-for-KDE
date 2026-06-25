from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

CornerName = Literal["top_left", "top_right", "bottom_right", "bottom_left"]
DirectionName = Literal["clockwise", "counter-clockwise"]
CORNER_SEQUENCE_CLOCKWISE: tuple[CornerName, ...] = (
    "top_left",
    "top_right",
    "bottom_right",
    "bottom_left",
)


@dataclass(frozen=True)
class AnchorMappingResult:
    mapping: list[int]
    direction: Literal["clockwise", "counter-clockwise"]
    ordered_corners: list[tuple[CornerName, int]]
    edge_lengths: list[int]


@dataclass(frozen=True)
class AnchorValidationResult:
    valid: bool
    errors: list[str]


def corner_anchors_from_mapping(
    anchors: dict[str, int | None],
) -> dict[CornerName, int | None]:
    return {name: anchors.get(name) for name in CORNER_SEQUENCE_CLOCKWISE}


def validate_corner_anchors(
    *, anchors: dict[CornerName, int | None], device_zone_count: int
) -> AnchorValidationResult:
    total = max(0, int(device_zone_count))
    errors: list[str] = []
    if total <= 0:
        errors.append("Device zone count must be at least 1.")
        return AnchorValidationResult(valid=False, errors=errors)

    missing = [name for name in CORNER_SEQUENCE_CLOCKWISE if anchors.get(name) is None]
    if missing:
        readable = ", ".join(name.replace("_", "-") for name in missing)
        errors.append(f"Missing corner anchors: {readable}.")
        return AnchorValidationResult(valid=False, errors=errors)

    values = {name: int(cast(int, anchors[name])) for name in CORNER_SEQUENCE_CLOCKWISE}
    for name, idx in values.items():
        if idx < 0 or idx >= total:
            errors.append(f"Anchor {name.replace('_', '-')}={idx} is outside 0..{total - 1}.")

    unique = set(values.values())
    if len(unique) != 4:
        errors.append("Each corner must map to a unique physical strip zone.")

    if total < 4:
        errors.append("At least 4 strip zones are required for four-corner calibration.")

    return AnchorValidationResult(valid=not errors, errors=errors)


def _cw_distance(a: int, b: int, total: int) -> int:
    return (int(b) - int(a)) % int(total)


def _choose_direction(
    values: dict[CornerName, int], total: int
) -> tuple[DirectionName, list[tuple[CornerName, int]], list[int]]:
    cw_order: list[tuple[CornerName, int]] = [
        ("top_left", values["top_left"]),
        ("top_right", values["top_right"]),
        ("bottom_right", values["bottom_right"]),
        ("bottom_left", values["bottom_left"]),
    ]
    ccw_order: list[tuple[CornerName, int]] = [
        ("top_left", values["top_left"]),
        ("bottom_left", values["bottom_left"]),
        ("bottom_right", values["bottom_right"]),
        ("top_right", values["top_right"]),
    ]

    cw_lengths = [_cw_distance(cw_order[i][1], cw_order[(i + 1) % 4][1], total) for i in range(4)]
    ccw_lengths = [
        _cw_distance(ccw_order[i][1], ccw_order[(i + 1) % 4][1], total) for i in range(4)
    ]

    ideal = float(total) / 4.0
    cw_score = sum((length - ideal) ** 2 for length in cw_lengths)
    ccw_score = sum((length - ideal) ** 2 for length in ccw_lengths)
    if ccw_score < cw_score:
        return "counter-clockwise", ccw_order, ccw_lengths
    return "clockwise", cw_order, cw_lengths


def derive_anchor_zone_map(
    *,
    zone_count: int,
    device_zone_count: int,
    anchors: dict[CornerName, int | None],
    source_side_counts: tuple[int, int, int, int] | None = None,
) -> AnchorMappingResult:
    validation = validate_corner_anchors(anchors=anchors, device_zone_count=device_zone_count)
    if not validation.valid:
        raise ValueError("; ".join(validation.errors))

    src_total = max(1, int(zone_count))
    dst_total = int(device_zone_count)
    values = {name: int(cast(int, anchors[name])) for name in CORNER_SEQUENCE_CLOCKWISE}

    direction, ordered_corners, edge_lengths = _choose_direction(values, dst_total)

    if source_side_counts is not None and sum(source_side_counts) == src_total:
        top, right, bottom, left = [max(0, int(v)) for v in source_side_counts]
        boundary_tr = top
        boundary_br = top + right
        boundary_bl = top + right + bottom
        if direction == "clockwise":
            source_corners = [0, boundary_tr, boundary_br, boundary_bl, src_total]
        else:
            source_corners = [0, boundary_bl, boundary_br, boundary_tr, src_total]
    else:
        if direction == "clockwise":
            source_corners = [0, src_total // 4, src_total // 2, (3 * src_total) // 4, src_total]
        else:
            source_corners = [0, (3 * src_total) // 4, src_total // 2, src_total // 4, src_total]

    mapping = [0] * dst_total
    for edge_idx in range(4):
        start_corner = ordered_corners[edge_idx][1]
        steps = edge_lengths[edge_idx]
        src_start = source_corners[edge_idx]
        src_end = source_corners[edge_idx + 1]
        if steps <= 0:
            continue
        for step in range(steps):
            device_idx = (start_corner + step) % dst_total
            t = step / steps
            src_idx = int(round(src_start + (src_end - src_start) * t)) % src_total
            mapping[device_idx] = src_idx

    return AnchorMappingResult(
        mapping=mapping,
        direction=direction,
        ordered_corners=[(name, int(idx)) for name, idx in ordered_corners],
        edge_lengths=edge_lengths,
    )
