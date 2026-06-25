from __future__ import annotations

import numpy as np

from nanoleaf_sync.capture.source_context import build_portal_display_source_context
from nanoleaf_sync.capture.source_identity import SourceIdentityTracker
from nanoleaf_sync.color.capture_metadata import CaptureMetadata
from nanoleaf_sync.color.metadata_hysteresis import MetadataHysteresisTracker
from nanoleaf_sync.device.send_policy import (
    LiveSendPolicy,
    LiveSendPolicyDecision,
    degrade_policy_on_missed_acks,
)
from nanoleaf_sync.runtime.color_domain import ColorDomain, infer_color_domain, to_linear_srgb
from nanoleaf_sync.runtime.color_pipeline import _resolve_live_sampling_mode
from nanoleaf_sync.runtime.color_processing import (
    LedCalibration,
    apply_display_gamut_adaptation,
    apply_led_calibration,
)
from nanoleaf_sync.runtime.status_warnings import build_runtime_warnings
from nanoleaf_sync.runtime.virtual_zones import virtual_zone_samples
from nanoleaf_sync.tools.colour_path_probe import compare_colour_path_stages


def test_metadata_hysteresis_requires_multiple_frames() -> None:
    tracker = MetadataHysteresisTracker(frames_required=3)
    first = CaptureMetadata(source="backend", confidence="backend")
    flip = CaptureMetadata(source="heuristic", confidence="heuristic")
    assert tracker.update(first).source == "backend"
    assert tracker.update(flip).source == "backend"
    assert tracker.update(flip).source == "backend"
    assert tracker.update(flip).source == "heuristic"


def test_metadata_hysteresis_bypasses_unknown_confidence() -> None:
    tracker = MetadataHysteresisTracker(frames_required=3)
    first = CaptureMetadata(source="backend", confidence="backend")
    unknown = CaptureMetadata(source="kwin display-referred", confidence="unknown")

    assert tracker.update(first).source == "backend"
    assert tracker.update(unknown) == unknown
    assert tracker.candidate is None


def test_portal_source_uses_compositor_layout_scale_confidence() -> None:
    class _Backend:
        last_stream_properties = {
            "id": 7,
            "size": {"width": 2560, "height": 1440},
            "pipewire-serial": 42,
        }
        portal_restore_token_state = "restored_confirmed"
        last_capture_path = "xdg-portal:pipewire"

    ctx = build_portal_display_source_context(_Backend(), frame_width=3840, frame_height=2160)
    assert ctx.scale_confidence == "compositor-layout"
    assert ctx.stream_pixel_size == (3840, 2160)


def test_source_identity_tracker_detects_changes() -> None:
    from nanoleaf_sync.runtime.frame_context import DisplaySourceContext

    tracker = SourceIdentityTracker()
    base = DisplaySourceContext(
        backend="kwin-dbus",
        monitor_id="DP-1",
        backend_source_id="DP-1",
        pipewire_serial=None,
        compositor_position=None,
        compositor_size=None,
        stream_pixel_size=(1920, 1080),
        display_pixel_size=(1920, 1080),
        scale_x=1.0,
        scale_y=1.0,
        refresh_hz=None,
        hdr_metadata=CaptureMetadata(source="backend", confidence="backend"),
        source_confidence="explicit",
    )
    _, first_change = tracker.observe(base, hdr_metadata_confidence="backend")
    assert first_change is False
    moved = DisplaySourceContext(
        backend=base.backend,
        monitor_id="DP-2",
        backend_source_id="DP-2",
        pipewire_serial=base.pipewire_serial,
        compositor_position=base.compositor_position,
        compositor_size=base.compositor_size,
        stream_pixel_size=base.stream_pixel_size,
        display_pixel_size=base.display_pixel_size,
        scale_x=base.scale_x,
        scale_y=base.scale_y,
        refresh_hz=base.refresh_hz,
        hdr_metadata=base.hdr_metadata,
        source_confidence=base.source_confidence,
    )
    _, changed = tracker.observe(moved, hdr_metadata_confidence="backend")
    assert changed is True


def test_ack_degrade_policy_on_high_miss_rate() -> None:
    decision = LiveSendPolicyDecision(
        policy=LiveSendPolicy.WRITE_ONLY,
        response_wait_skipped=True,
        transition_reason="test",
        requires_frame_ack=False,
    )
    degraded = degrade_policy_on_missed_acks(decision, missed_ack_rate=0.5)
    assert degraded.policy == LiveSendPolicy.RESPONSE_REQUIRED


def test_sampling_mode_dwell_holds_transition() -> None:
    mode, area, dwell = _resolve_live_sampling_mode(
        resolved_sampling_mode="edge_direct",
        prior_zone_sample_motion=20.0,
        prior_area_average_mode=False,
        dwell_remaining=2,
    )
    assert mode == "edge_direct"
    assert area is False
    assert dwell == 1


def test_color_domain_linear_calibration_order() -> None:
    colors = np.array([[128.0, 64.0, 32.0]], dtype=np.float32)
    assert infer_color_domain(colors) == ColorDomain.ENCODED_SRGB_U8
    linear = to_linear_srgb(colors)
    assert linear.max() <= 1.0
    calibrated = apply_led_calibration(
        colors,
        LedCalibration(red_gain=1.2, color_matrix=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)),
    )
    assert calibrated.shape == colors.shape


def test_color_domain_detects_uint8_before_float_conversion() -> None:
    colors = np.array([[1, 1, 1]], dtype=np.uint8)
    assert infer_color_domain(colors) == ColorDomain.ENCODED_SRGB_U8


def test_virtual_zone_samples_preserves_requested_count() -> None:
    frame = np.zeros((20, 40, 3), dtype=np.uint8)
    colors = virtual_zone_samples(frame, 10)
    assert colors.shape == (10, 3)


def test_gamut_adaptation_accepts_explicit_domain() -> None:
    colors = np.array([[0.5, 0.5, 0.5]], dtype=np.float32)
    out = apply_display_gamut_adaptation(
        colors,
        input_domain=ColorDomain.ENCODED_SRGB_FLOAT,
    )
    assert out.dtype == np.float32


def test_runtime_warnings_surface_primary_default_and_heuristic_hdr() -> None:
    warnings = build_runtime_warnings(
        status={
            "latest_frame_context": {
                "source": {"source_confidence": "primary-default", "scale_confidence": "fallback"}
            },
            "latest_color_context": {"confidence": "heuristic"},
            "hdr_colour_path": {"capture_metadata_source": "kwin display-referred"},
        }
    )
    assert any("primary" in w.lower() for w in warnings)
    assert any("heuristic" in w.lower() for w in warnings)


def test_colour_path_probe_reports_stage_deltas() -> None:
    report = compare_colour_path_stages(
        captured_rgb=(100, 120, 140),
        staged_outputs={
            "capture": (100, 120, 140),
            "hdr": (110, 125, 145),
            "output": (115, 130, 150),
        },
    )
    assert report["final_rgb"] == (115, 130, 150)
    assert len(report["stages"]) == 3
