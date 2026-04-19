from __future__ import annotations

import threading

import numpy as np

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.runtime.engine import (
    PendingFrameSlot,
    _adaptive_one_euro_blend,
    _ensure_runtime_artifacts,
    process_frame,
)
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


def test_runtime_artifacts_use_detected_device_zone_count_when_config_is_auto() -> None:
    state = RuntimeState()
    cfg = AppConfig(
        zones=[ZoneConfig(x=0.0, y=0.0, w=0.5, h=1.0), ZoneConfig(x=0.5, y=0.0, w=0.5, h=1.0)],
        device_zone_count=0,
    )

    _, mapping = _ensure_runtime_artifacts(
        state=state,
        config=cfg,
        img_w=100,
        img_h=50,
        detected_device_zone_count=5,
    )

    assert mapping.tolist() == [0, 1, 0, 1, 0]


def test_runtime_artifacts_manual_device_zone_count_overrides_detected_length() -> None:
    state = RuntimeState()
    cfg = AppConfig(
        zones=[ZoneConfig(x=0.0, y=0.0, w=0.5, h=1.0), ZoneConfig(x=0.5, y=0.0, w=0.5, h=1.0)],
        device_zone_count=3,
    )

    _, mapping = _ensure_runtime_artifacts(
        state=state,
        config=cfg,
        img_w=100,
        img_h=50,
        detected_device_zone_count=10,
    )

    assert mapping.tolist() == [0, 1, 0]


def test_process_frame_supports_zone_sampling_stride() -> None:
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    frame[:, :2] = [10, 20, 30]
    frame[:, 2:] = [50, 60, 70]
    zones_px = [(0, 0, 2, 4), (2, 0, 2, 4)]

    colors = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=[0, 1],
        brightness=1.0,
        smoothing=1.0,
        zone_sampling_stride=2,
    )

    assert colors == [(10, 20, 30), (50, 60, 70)]


def test_adaptive_smoothing_is_more_responsive_on_large_deltas() -> None:
    prev = np.array([[10.0, 10.0, 10.0], [10.0, 10.0, 10.0]], dtype=np.float32)
    current = np.array([[14.0, 10.0, 10.0], [200.0, 10.0, 10.0]], dtype=np.float32)

    out = _adaptive_one_euro_blend(current=current, previous=prev, smoothing=0.25)
    # Small delta remains strongly smoothed.
    assert out[0, 0] < 13.0
    # Large delta gets a much larger current-frame contribution.
    assert out[1, 0] > 150.0


def test_run_loop_skips_tick_when_backends_temporarily_missing() -> None:
    from nanoleaf_sync.runtime.engine import run_loop

    cfg = AppConfig(fps=120, verbose=False, use_mock_capture=False)
    state = RuntimeState()
    capture_calls = {"count": 0}

    def get_capture():
        capture_calls["count"] += 1
        return None

    stop_timer = threading.Timer(0.02, state.stop_event.set)
    stop_timer.start()
    # Should return cleanly even if providers currently return None.
    run_loop(
        config=cfg,
        state=state,
        get_capture=get_capture,
        get_driver=lambda: None,
        install_drivers=lambda: None,
        close_backends=lambda: None,
    )
    stop_timer.cancel()
    assert capture_calls["count"] >= 1


def test_pending_frame_slot_last_write_wins() -> None:
    slot = PendingFrameSlot()
    frame_a = np.zeros((1, 1, 3), dtype=np.uint8)
    frame_b = np.ones((1, 1, 3), dtype=np.uint8) * 255

    slot.put_latest(frame=frame_a, captured_at=1.0)
    slot.put_latest(frame=frame_b, captured_at=2.0)

    pending = slot.pop()
    assert pending is not None
    assert pending.captured_at == 2.0
    assert np.array_equal(pending.frame, frame_b)
    assert slot.get_replaced_count() == 1


def test_process_frame_applies_compositor_hdr_compensation() -> None:
    frame = np.full((2, 2, 3), 100, dtype=np.uint8)

    baseline = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=[(0, 0, 2, 2)],
        device_zone_indices=[0],
        brightness=1.0,
        smoothing=1.0,
        compositor_hdr_mode=False,
    )[0]

    boosted = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=[(0, 0, 2, 2)],
        device_zone_indices=[0],
        brightness=1.0,
        smoothing=1.0,
        compositor_hdr_mode=True,
        sdr_boost_nits=320.0,
        hdr_max_nits=1000.0,
    )[0]

    assert sum(boosted) > sum(baseline)


def test_process_frame_skips_compositor_when_boost_is_effectively_noop(monkeypatch) -> None:
    frame = np.full((2, 2, 3), 100, dtype=np.uint8)
    called = {"count": 0}

    def _fake_apply(*args, **kwargs):
        called["count"] += 1
        return np.full((2, 2, 3), 255, dtype=np.uint8)

    monkeypatch.setattr("nanoleaf_sync.runtime.engine.apply_sdr_boost_compensation", _fake_apply)

    out = process_frame(
        frame=frame,
        prev_smoothed_colors=[],
        zones_px=[(0, 0, 2, 2)],
        device_zone_indices=[0],
        brightness=1.0,
        smoothing=1.0,
        compositor_hdr_mode=True,
        sdr_boost_nits=80.0,
        hdr_max_nits=1000.0,
    )[0]

    assert called["count"] == 0
    assert out == (100, 100, 100)
