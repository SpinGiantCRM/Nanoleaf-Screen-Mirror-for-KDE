from __future__ import annotations

from nanoleaf_sync.capture.kwin_dbus import KWinDBusScreenshotCapture
from nanoleaf_sync.capture.source_context import (
    build_kwin_display_source_context,
    parse_portal_stream_properties,
)
from nanoleaf_sync.runtime.frame_context import build_frame_context


def test_kwin_display_source_context_primary_default() -> None:
    backend = KWinDBusScreenshotCapture(width=480, height=270, monitor_id="")
    ctx = build_kwin_display_source_context(backend, frame_width=480, frame_height=270)
    assert ctx.backend == "kwin-dbus"
    assert ctx.source_confidence == "primary-default"
    assert ctx.capture_method_confidence == "plasma-primary-empty-name"
    backend.close()


def test_kwin_display_source_context_preserves_skip_gamut_from_hdr_diagnostics() -> None:
    class _Backend:
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

    ctx = build_kwin_display_source_context(_Backend(), frame_width=64, frame_height=36)
    assert ctx.hdr_metadata.skip_display_gamut_adaptation is True


def test_frame_context_carries_seq_and_timing() -> None:
    backend = KWinDBusScreenshotCapture(width=64, height=36, monitor_id="DP-1")
    source = build_kwin_display_source_context(backend, frame_width=64, frame_height=36)
    frame_ctx = build_frame_context(
        frame_seq=7,
        captured_at=100.0,
        source=source,
        frame_width=64,
        frame_height=36,
        precomputed_zone_colors=False,
        capture_duration_ms=3.5,
    )
    assert frame_ctx.frame_seq == 7
    assert frame_ctx.capture_duration_ms == 3.5
    assert frame_ctx.source.monitor_id == "DP-1"
    backend.close()


def test_portal_stream_properties_parse_serial_and_size() -> None:
    props = parse_portal_stream_properties(
        (
            42,
            {
                "position": {"x": 0, "y": 0},
                "size": {"width": 3840, "height": 2160},
                "pipewire-serial": 99,
                "source_type": 1,
            },
        )
    )
    assert props["id"] == 42
    assert props["pipewire-serial"] == 99
    assert props["size"] == {"width": 3840, "height": 2160}


def test_portal_stream_properties_legacy_node_only() -> None:
    props = parse_portal_stream_properties((17, {}))
    assert props["id"] == 17
    assert "pipewire-serial" not in props
