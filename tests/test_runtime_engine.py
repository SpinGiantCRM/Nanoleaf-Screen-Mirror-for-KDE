from __future__ import annotations

import numpy as np

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.runtime.engine import _ensure_runtime_artifacts, process_frame
from nanoleaf_sync.runtime.state import RuntimeState


def test_runtime_artifacts_cached_until_signature_changes() -> None:
    state = RuntimeState()
    cfg = AppConfig(
        zones=[ZoneConfig(x=0.0, y=0.0, w=0.5, h=1.0), ZoneConfig(x=0.5, y=0.0, w=0.5, h=1.0)],
        device_zone_count=2,
        zone_offset=1,
    )

    zones_px_1, mapping_1 = _ensure_runtime_artifacts(
        state=state,
        config=cfg,
        img_w=100,
        img_h=50,
    )
    zones_px_2, mapping_2 = _ensure_runtime_artifacts(
        state=state,
        config=cfg,
        img_w=100,
        img_h=50,
    )

    assert zones_px_1 is zones_px_2
    assert mapping_1 is mapping_2

    # Resolution change must invalidate zone rectangles cache.
    zones_px_3, _ = _ensure_runtime_artifacts(
        state=state,
        config=cfg,
        img_w=120,
        img_h=50,
    )
    assert zones_px_3 is not zones_px_1

    # Mapping config change must invalidate mapping cache.
    cfg.zone_offset = 0
    _, mapping_3 = _ensure_runtime_artifacts(
        state=state,
        config=cfg,
        img_w=120,
        img_h=50,
    )
    assert mapping_3 is not mapping_2


def test_process_frame_uses_precomputed_artifacts() -> None:
    frame = np.array(
        [
            [[255, 0, 0], [255, 0, 0], [0, 255, 0], [0, 255, 0]],
            [[255, 0, 0], [255, 0, 0], [0, 255, 0], [0, 255, 0]],
        ],
        dtype=np.uint8,
    )
    zones_px = [(0, 0, 2, 2), (2, 0, 2, 2)]

    colors = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=[1, 0],
        brightness=1.0,
        smoothing=1.0,
    )

    assert colors == [(0, 255, 0), (255, 0, 0)]
