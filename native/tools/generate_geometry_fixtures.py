"""Shared layout/physical calibration oracle from the preserved Python runtime."""

import json
from pathlib import Path

import numpy as np

from nanoleaf_sync.runtime.anchor_calibration import derive_anchor_zone_map
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.runtime.zone_presets import (
    apply_layout_transform,
    edge_side_counts,
    make_edge_weighted_zones,
)

rng = np.random.default_rng(1117)
cases = []
for count in (4, 5, 8, 16, 48, 97, 192):
    for w, h in ((73, 41), (1920, 1080), (3840, 2160), (40, 900)):
        for locality in ("tight", "balanced", "wide"):
            inset, scale = (0.0, 1.0) if locality == "balanced" else (0.08, 0.87)
            zones = make_edge_weighted_zones(count, width=w, height=h, edge_locality=locality)
            counts = edge_side_counts(zone_count=count, width=w, height=h)
            zones = apply_layout_transform(zones, inset=inset, scale=scale)
            anchors = [int(v) for v in rng.choice(count, 4, replace=False)]
            mapping = derive_anchor_zone_map(
                zone_count=count,
                device_zone_count=count,
                anchors=dict(
                    zip(
                        ("top_left", "top_right", "bottom_right", "bottom_left"),
                        anchors,
                        strict=True,
                    )
                ),
                source_side_counts=counts,
            ).mapping
            cases.append(
                dict(
                    count=count,
                    width=w,
                    height=h,
                    locality=locality,
                    inset=inset,
                    scale=scale,
                    anchors=anchors,
                    zones=zones_from_config(zones, w, h),
                    counts=counts,
                    mapping=mapping,
                )
            )
Path(__file__).resolve().parents[1].joinpath("fixtures/geometry.json").write_text(
    json.dumps(cases, separators=(",", ":")) + "\n"
)
