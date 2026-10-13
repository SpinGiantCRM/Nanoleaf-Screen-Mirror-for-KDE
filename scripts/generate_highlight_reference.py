"""Refresh Rust highlight golden values from the unchanged Python reference.

Pixel cases remain in the fixture; this tool changes only expected values/modes.
Runtime does not depend on this Python oracle.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from nanoleaf_sync.runtime.srgb import srgb_u8_to_linear01
from nanoleaf_sync.runtime.zones import (
    _dark_biased_patch_mean,
    _low_light_patch_mean,
    _patch_peak_and_chroma,
    _peak_luma_zone_mean,
    _vivid_weighted_zone_mean,
    detect_zone_patch_mixed_content,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture", type=Path, default=Path("native/fixtures/highlight-policies.json")
    )
    path = parser.parse_args().fixture
    cases = json.loads(path.read_text())
    for case in cases:
        patch = np.asarray(case["pixels"], dtype=np.uint8).reshape(8, 8, 3)
        mode = case["mode"]
        assert mode in {"peak_luma", "vivid_weighted"}
        effective = mode
        if detect_zone_patch_mixed_content(patch):
            rgb = _dark_biased_patch_mean(patch)
            effective = "area_average"
        elif _patch_peak_and_chroma(patch)[0] < 0.0144:
            rgb = _low_light_patch_mean(patch)
            effective = "area_average"
        else:
            function = _peak_luma_zone_mean if mode == "peak_luma" else _vivid_weighted_zone_mean
            rgb = function(srgb_u8_to_linear01(patch))
        case["rgb"] = rgb.tolist()
        case["effective"] = effective
    path.write_text(json.dumps(cases, separators=(",", ":")) + "\n")
    print(f"Refreshed {len(cases)} reference cases")


if __name__ == "__main__":
    main()
