"""Generate native temporal stage oracles from the preserved Python implementation."""

from pathlib import Path
import json
import numpy as np
from nanoleaf_sync.runtime.blending import (
    BlendHysteresisState,
    adaptive_one_euro_blend,
    apply_neighbor_blend,
)

rng = np.random.default_rng(761)
cases = []
for preset in ("responsive", "calm", "dynamic"):
    for spread in ("off", "precise", "balanced", "soft"):
        state = BlendHysteresisState()
        previous = np.zeros((48, 3), dtype=np.float32)
        frames = []
        for index in range(48):
            current = rng.uniform(0, 255, (48, 3)).astype(np.float32)
            if index % 6 == 1:
                current = np.clip(previous + rng.uniform(-2, 2, (48, 3)), 0, 255).astype(np.float32)
            elif index % 6 == 2:
                current = np.repeat(rng.uniform(0, 35, (48, 1)), 3, axis=1).astype(np.float32)
            elif index % 6 == 3:
                current.fill(0)
            before = current.copy()
            current, state = apply_neighbor_blend(current, spread_mode=spread, hysteresis=state)
            current, _, state = adaptive_one_euro_blend(
                current=current,
                previous=previous,
                smoothing=0.5,
                smoothing_speed=0.75,
                motion_preset=preset,
                hysteresis=state,
            )
            frames.append(
                {
                    "input": before.tolist(),
                    "previous": previous.tolist(),
                    "expected": current.tolist(),
                }
            )
            previous = current
        cases.append({"preset": preset, "spread": spread, "frames": frames})
Path(__file__).resolve().parents[1].joinpath("fixtures/blending.json").write_text(
    json.dumps(cases, separators=(",", ":")) + "\n"
)
