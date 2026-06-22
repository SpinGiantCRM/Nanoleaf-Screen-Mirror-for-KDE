from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from nanoleaf_sync.color.capture_metadata import CaptureMetadata

SourceConfidence = Literal[
    "explicit",
    "restored",
    "primary-default",
    "fallback",
    "unknown",
]
CaptureMethodConfidence = Literal[
    "explicit-monitor",
    "plasma-primary-empty-name",
    "area-from-enumerated-monitor-rect",
    "legacy-fallback",
    "portal-restored",
    "portal-prompt",
    "unknown",
]


@dataclass(frozen=True)
class DisplaySourceContext:
    backend: str
    monitor_id: str | None
    backend_source_id: str | None
    pipewire_serial: int | None
    compositor_position: tuple[int, int] | None
    compositor_size: tuple[int, int] | None
    stream_pixel_size: tuple[int, int]
    display_pixel_size: tuple[int, int] | None
    scale_x: float
    scale_y: float
    refresh_hz: float | None
    hdr_metadata: CaptureMetadata
    source_confidence: SourceConfidence
    capture_method: str = ""
    capture_method_confidence: CaptureMethodConfidence = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "monitor_id": self.monitor_id,
            "backend_source_id": self.backend_source_id,
            "pipewire_serial": self.pipewire_serial,
            "compositor_position": self.compositor_position,
            "compositor_size": self.compositor_size,
            "stream_pixel_size": self.stream_pixel_size,
            "display_pixel_size": self.display_pixel_size,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "refresh_hz": self.refresh_hz,
            "hdr_metadata": self.hdr_metadata.as_dict(),
            "source_confidence": self.source_confidence,
            "capture_method": self.capture_method,
            "capture_method_confidence": self.capture_method_confidence,
        }


@dataclass(frozen=True)
class FrameContext:
    frame_seq: int
    captured_at_monotonic: float
    source: DisplaySourceContext
    frame_size: tuple[int, int]
    precomputed_zone_colors: bool
    capture_method: str
    capture_duration_ms: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "frame_seq": self.frame_seq,
            "captured_at_monotonic": self.captured_at_monotonic,
            "source": self.source.as_dict(),
            "frame_size": self.frame_size,
            "precomputed_zone_colors": self.precomputed_zone_colors,
            "capture_method": self.capture_method,
            "capture_duration_ms": self.capture_duration_ms,
        }


def default_display_source_context(
    *,
    backend: str,
    width: int,
    height: int,
) -> DisplaySourceContext:
    return DisplaySourceContext(
        backend=str(backend or "unknown"),
        monitor_id=None,
        backend_source_id=None,
        pipewire_serial=None,
        compositor_position=None,
        compositor_size=None,
        stream_pixel_size=(max(1, int(width)), max(1, int(height))),
        display_pixel_size=None,
        scale_x=1.0,
        scale_y=1.0,
        refresh_hz=None,
        hdr_metadata=CaptureMetadata(),
        source_confidence="unknown",
        capture_method="",
        capture_method_confidence="unknown",
    )


def build_frame_context(
    *,
    frame_seq: int,
    captured_at: float,
    source: DisplaySourceContext,
    frame_width: int,
    frame_height: int,
    precomputed_zone_colors: bool,
    capture_duration_ms: float,
) -> FrameContext:
    method = str(source.capture_method or source.backend or "unknown")
    return FrameContext(
        frame_seq=int(frame_seq),
        captured_at_monotonic=float(captured_at),
        source=source,
        frame_size=(max(1, int(frame_width)), max(1, int(frame_height))),
        precomputed_zone_colors=bool(precomputed_zone_colors),
        capture_method=method,
        capture_duration_ms=float(capture_duration_ms),
    )
