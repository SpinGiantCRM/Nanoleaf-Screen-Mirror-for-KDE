from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nanoleaf_sync.config.presets import analyzer_mode_for_presets
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.runtime.zone_presets import edge_weighted_layout, make_edge_weighted_zones
from nanoleaf_sync.runtime.zones import zone_colors_array


@dataclass(frozen=True)
class EdgeLocalityDiagnosticResult:
    summary: str
    far_edge_zones_stayed_dark: bool


def run_edge_locality_test(
    *,
    zone_count: int,
    edge_locality: str,
    sampling_quality: str,
    motion_preset: str,
    color_style: str,
    width: int = 320,
    height: int = 180,
) -> EdgeLocalityDiagnosticResult:
    stride = {"low": 4, "balanced": 2, "high": 1}.get(str(sampling_quality).lower(), 1)
    zones = make_edge_weighted_zones(
        zone_count, width=width, height=height, edge_locality=edge_locality
    )
    layout = edge_weighted_layout(
        zone_count=zone_count, width=width, height=height, edge_locality=edge_locality
    )
    zones_px = zones_from_config(zones, width=width, height=height)
    analyzer_mode = analyzer_mode_for_presets(motion_preset=motion_preset, color_style=color_style)

    edge_frame = np.zeros((height, width, 3), dtype=np.uint8)
    t = max(1, int(round(layout.edge_thickness * min(width, height))))
    edge_frame[:t, :, :] = np.array([255, 0, 0], dtype=np.uint8)
    edge_frame[:, width - t :, :] = np.array([0, 255, 0], dtype=np.uint8)
    edge_frame[height - t :, :, :] = np.array([0, 0, 255], dtype=np.uint8)
    edge_frame[:, :t, :] = np.array([255, 255, 255], dtype=np.uint8)

    _ = zone_colors_array(
        edge_frame, zones_px, sample_step=stride, mode=analyzer_mode, edge_locality=edge_locality
    )

    corner_frame = np.zeros((height, width, 3), dtype=np.uint8)
    corner_frame[height - t : height, :t, :] = np.array([0, 255, 0], dtype=np.uint8)
    corner_result = zone_colors_array(
        corner_frame, zones_px, sample_step=stride, mode=analyzer_mode, edge_locality=edge_locality
    )
    corner_colors = corner_result[0] if isinstance(corner_result, tuple) else corner_result

    top_n, right_n, bottom_n, left_n = layout.side_counts
    bottom_start = top_n + right_n
    bottom_start + bottom_n
    far_bottom = corner_colors[bottom_start : bottom_start + max(1, bottom_n // 2)]
    far_right = corner_colors[top_n : top_n + right_n]
    far_edge_mean = 0.0
    if far_bottom.size:
        far_edge_mean = max(far_edge_mean, float(far_bottom[:, 1].mean()))
    if far_right.size:
        far_edge_mean = max(far_edge_mean, float(far_right[:, 1].mean()))
    far_edge_dark = far_edge_mean < 20.0

    summary = (
        f"presets layout=edge_strip edge_locality={edge_locality} "
        f"sampling_quality={sampling_quality} motion={motion_preset} color={color_style} | "
        f"source_zones={len(zones)} strip_zones={zone_count} "
        f"sides(T/R/B/L)={layout.side_counts[0]}/{layout.side_counts[1]}/"
        f"{layout.side_counts[2]}/{layout.side_counts[3]} | "
        f"edge_thickness={layout.edge_thickness:.3f} sample_stride={stride} "
        f"analyzer_mode={analyzer_mode} "
        f"far_edge_dark={'yes' if far_edge_dark else 'no'}"
    )
    return EdgeLocalityDiagnosticResult(summary=summary, far_edge_zones_stayed_dark=far_edge_dark)
