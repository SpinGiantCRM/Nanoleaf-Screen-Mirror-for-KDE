from __future__ import annotations

import numpy as np

from nanoleaf_sync.color.capture_metadata import CaptureMetadata, resolve_capture_metadata
from nanoleaf_sync.runtime.color_context import (
    build_color_context,
    color_context_from_display_source,
)
from nanoleaf_sync.runtime.color_processing import (
    apply_display_gamut_adaptation,
    init_gamut_adaptation,
    set_skip_display_gamut_adaptation,
)
from nanoleaf_sync.runtime.frame_context import DisplaySourceContext


def _display_source(*, skip: bool, source: str) -> DisplaySourceContext:
    return DisplaySourceContext(
        backend="kwin-dbus",
        monitor_id=None,
        backend_source_id=None,
        pipewire_serial=None,
        compositor_position=None,
        compositor_size=None,
        stream_pixel_size=(64, 36),
        display_pixel_size=(64, 36),
        scale_x=1.0,
        scale_y=1.0,
        refresh_hz=None,
        hdr_metadata=CaptureMetadata(
            source=source,
            skip_display_gamut_adaptation=skip,
            confidence="backend" if skip else "heuristic",
        ),
        source_confidence="primary-default",
        capture_method="CaptureScreen",
    )


def test_sequential_frames_do_not_leak_skip_flag_via_color_context() -> None:
    init_gamut_adaptation("dci-p3")
    colors = np.array([[200.0, 100.0, 50.0]], dtype=np.float32)
    skip_ctx = build_color_context(
        metadata=CaptureMetadata(
            skip_display_gamut_adaptation=True,
            source="kwin display-referred",
        ),
    )
    apply_ctx = build_color_context(
        metadata=CaptureMetadata(skip_display_gamut_adaptation=False, source="backend"),
    )
    set_skip_display_gamut_adaptation(True)
    assert np.allclose(apply_display_gamut_adaptation(colors, color_context=skip_ctx), colors)
    adapted = apply_display_gamut_adaptation(colors, color_context=apply_ctx)
    global_skipped = apply_display_gamut_adaptation(colors)
    assert not np.allclose(adapted, global_skipped)
    set_skip_display_gamut_adaptation(False)
    init_gamut_adaptation("srgb")


def test_gamut_adaptation_preserves_float_input_without_premature_uint8_rounding() -> None:
    init_gamut_adaptation("srgb")
    colors = np.array([[120.4, 130.6, 140.2]], dtype=np.float32)
    ctx = build_color_context(metadata=CaptureMetadata(skip_display_gamut_adaptation=False))
    adapted = apply_display_gamut_adaptation(colors, color_context=ctx)
    assert adapted.dtype == np.float32
    assert adapted.max() <= 255.0


def test_hdr_fallback_emits_confidence_state() -> None:
    meta = resolve_capture_metadata(kwin_display_referred=True)
    ctx = color_context_from_display_source(_display_source(skip=True, source=meta.source))
    assert ctx.confidence in {"heuristic", "fallback", "unknown"}
    assert ctx.display_referred is True
