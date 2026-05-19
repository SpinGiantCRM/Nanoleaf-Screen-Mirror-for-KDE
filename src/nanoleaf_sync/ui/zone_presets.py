from __future__ import annotations

from dataclasses import dataclass
from typing import List

from nanoleaf_sync.config.model import ZoneConfig
from nanoleaf_sync.config.presets import edge_locality_profile


def make_horizontal_zones(zone_count: int) -> List[ZoneConfig]:
    count = max(1, int(zone_count))
    return [ZoneConfig(x=i / count, y=0.0, w=1.0 / count, h=1.0) for i in range(count)]


def _adaptive_edge_thickness(zone_count: int, *, edge_locality: str = "balanced") -> float:
    count = max(1, int(zone_count))
    low_count_thickness = 0.05
    target = edge_locality_profile(edge_locality).edge_thickness_target
    normalized = min(1.0, max(0.0, (count - 8) / 40.0))
    return low_count_thickness + (target - low_count_thickness) * normalized


def edge_side_counts(
    *, zone_count: int, width: int | None = None, height: int | None = None
) -> tuple[int, int, int, int]:
    count = max(1, int(zone_count))
    if count < 4:
        base = [0, 0, 0, 0]
        for idx in range(count):
            base[idx] += 1
        return tuple(base)

    w = max(1.0, float(width or 16))
    h = max(1.0, float(height or 9))
    side_lengths = [w, h, w, h]
    perimeter = sum(side_lengths)
    raw = [count * (length / perimeter) for length in side_lengths]
    assigned = [max(1, int(value)) for value in raw]

    remaining = count - sum(assigned)
    if remaining > 0:
        order = sorted(
            range(4), key=lambda idx: (raw[idx] - assigned[idx], side_lengths[idx]), reverse=True
        )
        for i in range(remaining):
            assigned[order[i % 4]] += 1
    elif remaining < 0:
        order = sorted(
            range(4), key=lambda idx: (assigned[idx] - raw[idx], side_lengths[idx]), reverse=True
        )
        to_remove = -remaining
        for idx in order:
            while to_remove > 0 and assigned[idx] > 1:
                assigned[idx] -= 1
                to_remove -= 1
            if to_remove == 0:
                break
    return tuple(assigned)


@dataclass(frozen=True)
class EdgeZoneLayout:
    side_counts: tuple[int, int, int, int]
    edge_thickness: float
    order_mode: str


def edge_weighted_layout(
    *,
    zone_count: int,
    width: int | None = None,
    height: int | None = None,
    edge_locality: str = "balanced",
) -> EdgeZoneLayout:
    count = max(1, int(zone_count))
    return EdgeZoneLayout(
        side_counts=edge_side_counts(zone_count=count, width=width, height=height),
        edge_thickness=_adaptive_edge_thickness(count, edge_locality=edge_locality),
        order_mode="continuous_perimeter",
    )


def make_edge_weighted_zones(
    zone_count: int,
    *,
    width: int | None = None,
    height: int | None = None,
    edge_locality: str = "balanced",
) -> List[ZoneConfig]:
    count = max(1, int(zone_count))
    layout = edge_weighted_layout(
        zone_count=count, width=width, height=height, edge_locality=edge_locality
    )
    top_n, right_n, bottom_n, left_n = layout.side_counts
    edge_thickness = layout.edge_thickness
    zones: List[ZoneConfig] = []
    for i in range(top_n):
        zones.append(ZoneConfig(x=i / top_n, y=0.0, w=1.0 / top_n, h=edge_thickness))
    for i in range(right_n):
        zones.append(
            ZoneConfig(x=1.0 - edge_thickness, y=i / right_n, w=edge_thickness, h=1.0 / right_n)
        )
    for i in range(bottom_n):
        zones.append(
            ZoneConfig(
                x=(bottom_n - 1 - i) / bottom_n,
                y=1.0 - edge_thickness,
                w=1.0 / bottom_n,
                h=edge_thickness,
            )
        )
    for i in range(left_n):
        zones.append(
            ZoneConfig(x=0.0, y=(left_n - 1 - i) / left_n, w=edge_thickness, h=1.0 / left_n)
        )
    return zones[:count]
