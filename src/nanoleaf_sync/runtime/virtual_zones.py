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
    per_side = max(1, count // 4)
    zones: list[ZoneRect] = []
    side_w = max(1, w // per_side)
    for i in range(per_side):
        zones.append((i * side_w, 0, side_w, edge_px))
    side_h = max(1, h // per_side)
    for i in range(per_side):
        zones.append((w - edge_px, i * side_h, edge_px, side_h))
    for i in range(per_side):
        zones.append((w - (i + 1) * side_w, h - edge_px, side_w, edge_px))
    for i in range(per_side):
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
