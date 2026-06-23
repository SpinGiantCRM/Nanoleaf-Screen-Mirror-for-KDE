from __future__ import annotations

import numpy as np
import pytest

from nanoleaf_sync.capture.source_context import (
    build_kwin_display_source_context,
    build_portal_display_source_context,
)
from nanoleaf_sync.capture.xdg_portal import XDGPortalCapture
from nanoleaf_sync.color.capture_metadata import resolve_capture_metadata
from nanoleaf_sync.runtime.color_context import color_context_from_display_source
from nanoleaf_sync.runtime.color_pipeline import ColorPipelineParams, process_zone_colors
from nanoleaf_sync.runtime.color_processing import (
    apply_display_gamut_adaptation,
    init_gamut_adaptation,
)
from nanoleaf_sync.runtime.engine import RuntimeState


class _PortalBackend:
    last_stream_properties: dict[str, object] = {
        "id": 7,
        "pipewire-serial": 42,
    }
    portal_restore_token_state = "restored_confirmed"
    last_capture_path = "xdg-portal:pipewire"
    last_hdr_diagnostics: dict[str, object] | None = None


def test_portal_display_source_context_uses_display_referred_srgb_metadata() -> None:
    ctx = build_portal_display_source_context(_PortalBackend(), frame_width=1920, frame_height=1080)
    meta = ctx.hdr_metadata
    assert meta.transfer == "srgb"
    assert meta.primaries == "bt709"
    assert meta.source == "xdg-portal display-referred"
    assert meta.skip_display_gamut_adaptation is True
    assert "display-referred" in meta.assumption.lower()


def test_portal_display_source_context_respects_reliable_backend_metadata() -> None:
    class _BackendWithHdr(_PortalBackend):
        last_hdr_diagnostics = {
            "transfer": "pq",
            "primaries": "bt2020",
            "max_nits": 1000.0,
            "source": "backend",
        }

    ctx = build_portal_display_source_context(
        _BackendWithHdr(), frame_width=1920, frame_height=1080
    )
    meta = ctx.hdr_metadata
    assert meta.transfer == "pq"
    assert meta.primaries == "bt2020"
    assert meta.source == "backend"
    assert meta.skip_display_gamut_adaptation is True


def test_portal_color_context_skips_display_gamut_adaptation_by_default() -> None:
    init_gamut_adaptation("dci-p3")
    ctx = build_portal_display_source_context(_PortalBackend(), frame_width=64, frame_height=36)
    color_ctx = color_context_from_display_source(ctx)
    assert color_ctx.display_referred is True
    assert color_ctx.skip_display_gamut_adaptation is True
    colors = np.array([[200.0, 100.0, 50.0]], dtype=np.float32)
    assert np.allclose(apply_display_gamut_adaptation(colors, color_context=color_ctx), colors)
    init_gamut_adaptation("srgb")


def test_portal_resolve_capture_metadata_matches_kwin_display_referred_defaults() -> None:
    portal_meta = resolve_capture_metadata(portal_display_referred=True)
    kwin_meta = resolve_capture_metadata(kwin_display_referred=True)
    assert portal_meta.transfer == kwin_meta.transfer == "srgb"
    assert portal_meta.primaries == kwin_meta.primaries == "bt709"
    assert portal_meta.skip_display_gamut_adaptation is True
    assert portal_meta.source == "xdg-portal display-referred"


def test_display_referred_portal_suppresses_sdr_boost_compensation() -> None:
    ctx = build_portal_display_source_context(_PortalBackend(), frame_width=64, frame_height=36)
    color_ctx = color_context_from_display_source(ctx)
    capture_display_referred = bool(color_ctx.display_referred)
    compositor_hdr_mode = True
    capture_backend_name = "xdg-portal"
    if capture_backend_name == "kwin-dbus":
        sdr_boost_compensation_enabled = compositor_hdr_mode
    else:
        sdr_boost_compensation_enabled = compositor_hdr_mode and not capture_display_referred
    assert capture_display_referred is True
    assert sdr_boost_compensation_enabled is False

    raw = np.asarray([[128, 128, 128]], dtype=np.uint8)
    zones_px = [(0, 0, 120, 80)]
    suppressed = ColorPipelineParams(
        compositor_hdr_mode=True,
        sdr_boost_nits=200.0,
        sdr_boost_compensation_enabled=sdr_boost_compensation_enabled,
        skip_display_gamut_adaptation=True,
        color_context=color_ctx,
        color_style="reference",
        return_diagnostics=True,
    )
    enabled = ColorPipelineParams(
        compositor_hdr_mode=True,
        sdr_boost_nits=200.0,
        sdr_boost_compensation_enabled=True,
        skip_display_gamut_adaptation=True,
        color_context=color_ctx,
        color_style="reference",
        return_diagnostics=True,
    )
    suppressed_out = process_zone_colors(
        frame=None,
        precomputed_zone_colors=raw,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=[0],
        params=suppressed,
    )
    enabled_out = process_zone_colors(
        frame=None,
        precomputed_zone_colors=raw,
        prev_smoothed_colors=[],
        zones_px=zones_px,
        device_zone_indices=[0],
        params=enabled,
    )
    suppressed_colors, *_rest, suppressed_timings, _smooth, _history = suppressed_out  # type: ignore[misc]
    enabled_colors, *_rest2, enabled_timings, _smooth2, _history2 = enabled_out  # type: ignore[misc]
    assert suppressed_timings.per_zone_sdr_boost_undo_ratio == ()
    assert enabled_timings.per_zone_sdr_boost_undo_ratio
    assert int(suppressed_colors[0][0]) > int(enabled_colors[0][0]) + 20


def test_kwin_display_referred_enables_sdr_boost_compensation_in_hdr_mode() -> None:
    class _KwinBackend:
        params = type("P", (), {"monitor_id": "DP-1", "width": 64, "height": 36})()
        last_capture_path = "kwin-dbus:screenshot2"
        last_hdr_diagnostics = {
            "transfer": "srgb",
            "primaries": "bt709",
            "max_nits": 1000.0,
            "skip_display_gamut_adaptation": True,
            "tone_mapping_applied": True,
            "source": "kwin display-referred",
        }

    ctx = build_kwin_display_source_context(_KwinBackend(), frame_width=64, frame_height=36)
    color_ctx = color_context_from_display_source(ctx)
    capture_display_referred = bool(color_ctx.display_referred)
    compositor_hdr_mode = True
    capture_backend_name = "kwin-dbus"
    if capture_backend_name == "kwin-dbus":
        sdr_boost_compensation_enabled = compositor_hdr_mode
    else:
        sdr_boost_compensation_enabled = compositor_hdr_mode and not capture_display_referred
    assert capture_display_referred is True
    assert sdr_boost_compensation_enabled is True


def test_runtime_state_reflects_suppressed_sdr_boost_for_display_referred_portal() -> None:
    state = RuntimeState()
    state.sdr_boost_compensation_enabled = False
    snapshot = state.status_snapshot(
        running=False,
        capture_backend_name="xdg-portal",
        capture_path="xdg-portal:pipewire",
        capture_width=1920,
        capture_height=1080,
        max_consecutive_errors=3,
        reinit_backoff_ms=250,
    )
    assert snapshot["sdr_boost_compensation_enabled"] is False


@pytest.mark.parametrize(
    ("fmt", "payload", "expected"),
    [
        ("RGB", bytes([255, 0, 0]), [255, 0, 0]),
        ("BGR", bytes([0, 0, 255]), [255, 0, 0]),
        ("RGBx", bytes([255, 0, 0, 0]), [255, 0, 0]),
        ("BGRx", bytes([0, 0, 255, 0]), [255, 0, 0]),
        ("RGBA", bytes([255, 0, 0, 128]), [255, 0, 0]),
        ("BGRA", bytes([0, 0, 255, 128]), [255, 0, 0]),
    ],
)
def test_portal_mapped_bytes_to_rgb_preserves_red(
    fmt: str, payload: bytes, expected: list[int]
) -> None:
    backend = XDGPortalCapture(width=1, height=1)
    frame = backend._mapped_bytes_to_rgb(payload=payload, width=1, height=1, fmt=fmt, stride=None)
    assert frame is not None
    assert frame[0, 0].tolist() == expected


@pytest.mark.parametrize(
    ("fmt", "payload", "expected"),
    [
        ("RGB", bytes([0, 255, 0]), [0, 255, 0]),
        ("BGR", bytes([0, 255, 0]), [0, 255, 0]),
        ("RGBx", bytes([0, 255, 0, 0]), [0, 255, 0]),
        ("BGRx", bytes([0, 255, 0, 0]), [0, 255, 0]),
        ("RGBA", bytes([0, 255, 0, 255]), [0, 255, 0]),
        ("BGRA", bytes([0, 255, 0, 255]), [0, 255, 0]),
    ],
)
def test_portal_mapped_bytes_to_rgb_preserves_green(
    fmt: str, payload: bytes, expected: list[int]
) -> None:
    backend = XDGPortalCapture(width=1, height=1)
    frame = backend._mapped_bytes_to_rgb(payload=payload, width=1, height=1, fmt=fmt, stride=None)
    assert frame is not None
    assert frame[0, 0].tolist() == expected


@pytest.mark.parametrize(
    ("fmt", "payload", "expected"),
    [
        ("RGB", bytes([0, 0, 255]), [0, 0, 255]),
        ("BGR", bytes([255, 0, 0]), [0, 0, 255]),
        ("RGBx", bytes([0, 0, 255, 0]), [0, 0, 255]),
        ("BGRx", bytes([255, 0, 0, 0]), [0, 0, 255]),
        ("RGBA", bytes([0, 0, 255, 255]), [0, 0, 255]),
        ("BGRA", bytes([255, 0, 0, 255]), [0, 0, 255]),
    ],
)
def test_portal_mapped_bytes_to_rgb_preserves_blue(
    fmt: str, payload: bytes, expected: list[int]
) -> None:
    backend = XDGPortalCapture(width=1, height=1)
    frame = backend._mapped_bytes_to_rgb(payload=payload, width=1, height=1, fmt=fmt, stride=None)
    assert frame is not None
    assert frame[0, 0].tolist() == expected


@pytest.mark.parametrize("fmt", ["RGB", "BGR", "RGBx", "BGRx", "RGBA", "BGRA"])
def test_portal_mapped_bytes_to_rgb_preserves_white(fmt: str) -> None:
    backend = XDGPortalCapture(width=1, height=1)
    payload = bytes([255, 255, 255]) if fmt in {"RGB", "BGR"} else bytes([255, 255, 255, 255])
    frame = backend._mapped_bytes_to_rgb(payload=payload, width=1, height=1, fmt=fmt, stride=None)
    assert frame is not None
    assert frame[0, 0].tolist() == [255, 255, 255]


@pytest.mark.parametrize(
    ("fmt", "payload", "expected"),
    [
        ("RGB", bytes([128, 255, 0]), [128, 255, 0]),
        ("BGR", bytes([0, 255, 128]), [128, 255, 0]),
        ("RGBx", bytes([128, 255, 0, 0]), [128, 255, 0]),
        ("BGRx", bytes([0, 255, 128, 0]), [128, 255, 0]),
        ("RGBA", bytes([128, 255, 0, 255]), [128, 255, 0]),
        ("BGRA", bytes([0, 255, 128, 255]), [128, 255, 0]),
    ],
)
def test_portal_mapped_bytes_to_rgb_preserves_yellow_green(
    fmt: str, payload: bytes, expected: list[int]
) -> None:
    backend = XDGPortalCapture(width=1, height=1)
    frame = backend._mapped_bytes_to_rgb(payload=payload, width=1, height=1, fmt=fmt, stride=None)
    assert frame is not None
    assert frame[0, 0].tolist() == expected
