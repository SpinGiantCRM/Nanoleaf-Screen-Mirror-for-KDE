import json
import statistics
import time
from pathlib import Path

import numpy as np

from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.runtime.srgb import linear01_to_srgb_u8, srgb_u8_to_linear01
from nanoleaf_sync.runtime.zone_presets import make_edge_weighted_zones
from nanoleaf_sync.runtime.zones import _zone_colors_via_box_filter, edge_anchored_rect


def reference(frame, zones):
    colors = []
    variances = []
    for zone in zones:
        x, y, w, h = edge_anchored_rect(zone, frame.shape[1], frame.shape[0])
        patch = frame[y : y + h, x : x + w, :3]
        colors.append(linear01_to_srgb_u8(srgb_u8_to_linear01(patch).reshape(-1, 3).mean(axis=0)))
        variances.append(float(np.var(patch.reshape(-1, 3).astype(np.float32), axis=0).mean()))
    return np.asarray(colors), np.asarray(variances)


def metric(fn):
    for _ in range(3):
        fn()
    samples = []
    for _ in range(20):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000)
    return {
        "samples": samples,
        "median_ms": statistics.median(samples),
        "p95_ms": sorted(samples)[18],
    }


rows = []
for width, height in [(640, 360), (2560, 1440), (3840, 2160)]:
    rng = np.random.default_rng(42)
    frame = rng.integers(0, 256, (height, width, 3), dtype=np.uint8)
    zones = zones_from_config(
        make_edge_weighted_zones(48, width=width, height=height, edge_locality="tight"),
        width,
        height,
    )

    def optimized(frame=frame, zones=zones):
        return _zone_colors_via_box_filter(
            frame, zones, edge_locality="tight", use_multi_moment=False
        )

    old, old_variances = reference(frame, zones)
    new, new_variances = optimized()
    rows.append(
        {
            "width": width,
            "height": height,
            "zones": 48,
            "seed": 42,
            "reference": metric(lambda frame=frame, zones=zones: reference(frame, zones)),
            "optimized": metric(optimized),
            "max_rgb_code_difference": int(
                np.max(np.abs(old.astype(np.int16) - new.astype(np.int16)))
            ),
            "max_encoded_variance_difference": float(np.max(np.abs(old_variances - new_variances))),
        }
    )
Path("perf/recovery-2026-10-12/sampling-comparison.json").write_text(
    json.dumps(rows, indent=2) + "\n"
)
print(
    json.dumps(
        [
            {k: v for k, v in r.items() if k not in ("reference", "optimized")}
            | {
                "reference_median_ms": r["reference"]["median_ms"],
                "optimized_median_ms": r["optimized"]["median_ms"],
            }
            for r in rows
        ],
        indent=2,
    )
)
