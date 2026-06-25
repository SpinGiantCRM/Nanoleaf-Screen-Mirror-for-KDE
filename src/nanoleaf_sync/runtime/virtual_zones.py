"""Virtual zone oversampling with polyphase projection to physical LEDs."""

from __future__ import annotations

import numpy as np

from nanoleaf_sync.capture._utils import zone_box_average
from nanoleaf_sync.runtime.zones import ZoneRect


def virtual_zone_samples(
    frame: np.ndarray,
    virtual_count: int,
    *,
    edge_thickness: float = 0.08,
) -> np.ndarray:
    h, w, _ = frame.shape
    count = max(1, int(virtual_count))
    edge_px = max(1, int(h * edge_thickness))
    base, remainder = divmod(count, 4)
    per_side_counts = [base + (1 if side < remainder else 0) for side in range(4)]
    per_side_counts = [max(1, side_count) for side_count in per_side_counts]
    zones: list[ZoneRect] = []
    top_count, right_count, bottom_count, left_count = per_side_counts
    side_w = max(1, w // top_count)
    for i in range(top_count):
        zones.append((i * side_w, 0, side_w, edge_px))
    side_h = max(1, h // right_count)
    for i in range(right_count):
        zones.append((w - edge_px, i * side_h, edge_px, side_h))
    side_w = max(1, w // bottom_count)
    for i in range(bottom_count):
        zones.append((w - (i + 1) * side_w, h - edge_px, side_w, edge_px))
    side_h = max(1, h // left_count)
    for i in range(left_count):
        zones.append((0, h - (i + 1) * side_h, edge_px, side_h))

    colors = np.zeros((len(zones), 3), dtype=np.uint8)
    for idx, zone in enumerate(zones):
        colors[idx] = zone_box_average(frame, zone)
    return colors


def project_to_physical(
    virtual_colors: np.ndarray,
    physical_count: int,
    mapping: np.ndarray | None = None,
) -> np.ndarray:
    virtual = np.asarray(virtual_colors, dtype=np.float32)
    physical = max(1, int(physical_count))
    if mapping is not None:
        mat = np.asarray(mapping, dtype=np.float32)
        return np.clip(virtual @ mat.T, 0, 255).astype(np.uint8)

    if virtual.shape[0] <= 1:
        return np.tile(virtual[:1], (physical, 1)).astype(np.uint8)

    indices = np.linspace(0, len(virtual) - 1, physical)
    lower = indices.astype(int)
    upper = np.clip(lower + 1, 0, len(virtual) - 1)
    frac = (indices - lower)[:, None]
    projected = virtual[lower] * (1.0 - frac) + virtual[upper] * frac
    return np.clip(projected, 0, 255).astype(np.uint8)
