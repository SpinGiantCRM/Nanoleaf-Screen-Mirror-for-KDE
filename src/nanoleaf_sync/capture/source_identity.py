from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from nanoleaf_sync.runtime.color_context import MetadataConfidence
from nanoleaf_sync.runtime.frame_context import DisplaySourceContext, SourceConfidence

ScaleConfidence = Literal[
    "pixel-exact",
    "compositor-layout",
    "fractional-unknown",
    "fallback",
]


@dataclass(frozen=True)
class CaptureSourceIdentity:
    backend: str
    session_generation: int
    source_confidence: SourceConfidence
    monitor_id: str | None
    backend_source_id: str | None
    pipewire_serial: int | None
    pipewire_node_id: int | None
    mapping_id: str | None
    compositor_position: tuple[int, int] | None
    compositor_layout_size: tuple[int, int] | None
    stream_pixel_size: tuple[int, int]
    display_pixel_size: tuple[int, int] | None
    scale_confidence: ScaleConfidence
    hdr_metadata_confidence: MetadataConfidence

    def fingerprint(self) -> str:
        return "|".join(
            (
                self.backend,
                str(self.session_generation),
                self.source_confidence,
                str(self.monitor_id or ""),
                str(self.backend_source_id or ""),
                str(self.pipewire_serial or ""),
                str(self.mapping_id or ""),
                f"{self.stream_pixel_size[0]}x{self.stream_pixel_size[1]}",
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "session_generation": self.session_generation,
            "source_confidence": self.source_confidence,
            "monitor_id": self.monitor_id,
            "backend_source_id": self.backend_source_id,
            "pipewire_serial": self.pipewire_serial,
            "pipewire_node_id": self.pipewire_node_id,
            "mapping_id": self.mapping_id,
            "compositor_position": self.compositor_position,
            "compositor_layout_size": self.compositor_layout_size,
            "stream_pixel_size": self.stream_pixel_size,
            "display_pixel_size": self.display_pixel_size,
            "scale_confidence": self.scale_confidence,
            "hdr_metadata_confidence": self.hdr_metadata_confidence,
            "fingerprint": self.fingerprint(),
        }


def _scale_confidence_for_source(source: DisplaySourceContext) -> ScaleConfidence:
    if source.compositor_size is not None and source.stream_pixel_size != source.compositor_size:
        return "compositor-layout"
    if (
        source.display_pixel_size is not None
        and source.stream_pixel_size == source.display_pixel_size
    ):
        return "pixel-exact"
    if source.source_confidence in {"primary-default", "fallback", "unknown"}:
        return "fallback"
    return "pixel-exact"


def build_capture_source_identity(
    source: DisplaySourceContext,
    *,
    session_generation: int = 0,
    hdr_metadata_confidence: MetadataConfidence = "unknown",
    mapping_id: str | None = None,
) -> CaptureSourceIdentity:
    node_id = None
    if source.backend == "xdg-portal" and source.backend_source_id is not None:
        try:
            node_id = int(source.backend_source_id)
        except (TypeError, ValueError):
            node_id = None
    return CaptureSourceIdentity(
        backend=source.backend,
        session_generation=int(session_generation),
        source_confidence=source.source_confidence,
        monitor_id=source.monitor_id,
        backend_source_id=source.backend_source_id,
        pipewire_serial=source.pipewire_serial,
        pipewire_node_id=node_id,
        mapping_id=mapping_id,
        compositor_position=source.compositor_position,
        compositor_layout_size=source.compositor_size,
        stream_pixel_size=source.stream_pixel_size,
        display_pixel_size=source.display_pixel_size,
        scale_confidence=_scale_confidence_for_source(source),
        hdr_metadata_confidence=hdr_metadata_confidence,
    )


@dataclass
class SourceIdentityTracker:
    session_generation: int = 0
    last_identity: CaptureSourceIdentity | None = None
    change_count: int = 0

    def observe(
        self,
        source: DisplaySourceContext,
        *,
        hdr_metadata_confidence: MetadataConfidence = "unknown",
    ) -> tuple[CaptureSourceIdentity, bool]:
        identity = build_capture_source_identity(
            source,
            session_generation=self.session_generation,
            hdr_metadata_confidence=hdr_metadata_confidence,
        )
        changed = False
        if (
            self.last_identity is not None
            and self.last_identity.fingerprint() != identity.fingerprint()
        ):
            changed = True
            self.change_count += 1
        self.last_identity = identity
        return identity, changed

    def bump_session(self) -> int:
        self.session_generation += 1
        self.last_identity = None
        return self.session_generation
