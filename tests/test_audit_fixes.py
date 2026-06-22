from __future__ import annotations

import numpy as np

from nanoleaf_sync.color.capture_metadata import (
    invalidate_plasma_hdr_cache,
    resolve_capture_metadata,
)
from nanoleaf_sync.color.zone_mapper import resolve_device_zone_indices
from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.device.send_policy import (
    LiveSendPolicy,
    LiveSendPolicyDecision,
    apply_periodic_ack_check,
)
from nanoleaf_sync.runtime.color_processing import (
    apply_output_quantization_hold,
    stabilize_dark_zone_samples,
)
from nanoleaf_sync.runtime.ring_buf import SPSCRingBuffer
from nanoleaf_sync.runtime.startup import reinitialize_backends
from nanoleaf_sync.runtime.state import RuntimeState
from nanoleaf_sync.runtime.zone_derivation import derive_source_zone_artifacts


def test_kwin_display_referred_skips_gamut_adaptation() -> None:
    meta = resolve_capture_metadata(kwin_display_referred=True)
    assert meta.skip_display_gamut_adaptation is True


def test_plasma_hdr_cache_invalidation_clears_cached_state() -> None:
    from nanoleaf_sync.color.capture_metadata import _plasma_hdr_enabled

    _plasma_hdr_enabled()
    invalidate_plasma_hdr_cache()
    assert _plasma_hdr_enabled.cache_info().currsize == 0


def test_reverse_zones_applied_with_fixed_mapping() -> None:
    mapping = [0, 10, 20, 30]
    forward = resolve_device_zone_indices(
        48,
        device_zone_count=4,
        reverse=False,
        fixed_mapping=mapping,
    )
    reversed_map = resolve_device_zone_indices(
        48,
        device_zone_count=4,
        reverse=True,
        fixed_mapping=mapping,
    )
    assert forward == mapping
    assert reversed_map == list(reversed(mapping))


def test_diagnostic_capture_falls_back_when_corner_anchors_missing() -> None:
    from nanoleaf_sync.service import NanoleafSyncService
    from tests.test_service_status_modes import FakeCapture, FakeDriver

    cfg = AppConfig(fps=30, use_mock_capture=False, device_zone_count=12, display_preset="hdr")
    capture = FakeCapture(name="kwin-dbus", width=640, height=360)
    svc = NanoleafSyncService(
        config=cfg, capture_backend_override=capture, driver_override=FakeDriver()
    )
    result = svc.capture_one_diagnostic_frame()
    assert result["ok"] is True, result.get("message")


def test_persisted_zones_keep_side_counts_on_ultrawide() -> None:
    cfg = AppConfig(
        zones=[ZoneConfig(x=0.0, y=0.0, w=0.1, h=0.1)] * 48,
        source_side_counts=[12, 8, 12, 16],
        device_zone_count=48,
    )
    artifacts = derive_source_zone_artifacts(
        config=cfg,
        frame_width=3440,
        frame_height=1440,
    )
    assert artifacts.side_counts == (12, 8, 12, 16)


def test_periodic_ack_check_forces_response_required_every_n_frames() -> None:
    decision = LiveSendPolicyDecision(
        policy=LiveSendPolicy.WRITE_ONLY,
        response_wait_skipped=True,
        transition_reason="test",
        requires_frame_ack=False,
    )
    unchanged = apply_periodic_ack_check(decision, live_frame_index=15, interval=30)
    assert unchanged.policy == LiveSendPolicy.WRITE_ONLY
    forced = apply_periodic_ack_check(decision, live_frame_index=30, interval=30)
    assert forced.policy == LiveSendPolicy.RESPONSE_REQUIRED
    assert forced.response_wait_skipped is False


def test_reinitialize_backends_clears_smoothing_history() -> None:
    state = RuntimeState()
    state.prev_sent_colors = [(1, 2, 3)]
    state.prev_smooth_float_colors = [(1.0, 2.0, 3.0)]
    state.smoothing_dimension_signature = (1920, 1080)
    reinitialize_backends(
        install_drivers=lambda: None,
        close_backends=lambda: None,
        state=state,
    )
    assert state.prev_sent_colors == []
    assert state.prev_smooth_float_colors == []
    assert state.smoothing_dimension_signature is None


def test_stabilize_dark_zone_samples_uses_schmidt_trigger_hold() -> None:
    colors = np.array([[2.0, 2.0, 2.0], [40.0, 40.0, 40.0]], dtype=np.float32)
    first, hold = stabilize_dark_zone_samples(colors)
    assert hold.shape == (2,)
    second, hold2 = stabilize_dark_zone_samples(colors, hold_mask=hold)
    assert hold2.shape == (2,)
    assert np.allclose(first[0], second[0])


def test_quantization_hold_scales_with_low_fps() -> None:
    current = np.array([[10.0, 10.0, 10.0]], dtype=np.float32)
    previous = np.array([[8.5, 8.5, 8.5]], dtype=np.float32)
    held_60 = apply_output_quantization_hold(current, previous, effective_target_fps=60.0)
    held_15 = apply_output_quantization_hold(current, previous, effective_target_fps=15.0)
    assert held_60[0, 0] == current[0, 0]
    assert held_15[0, 0] == previous[0, 0]


def test_ring_buffer_clear_empties_pending_items() -> None:
    buf: SPSCRingBuffer[int] = SPSCRingBuffer(capacity=2)
    assert buf.try_push(1) is True
    assert buf.try_push(2) is True
    cleared = buf.clear()
    assert cleared == 2
    assert buf.try_pop() is None
