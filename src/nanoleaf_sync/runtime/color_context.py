from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from nanoleaf_sync.color.capture_metadata import CaptureMetadata
from nanoleaf_sync.runtime.color_processing import get_gamut_adaptation_matrix
from nanoleaf_sync.runtime.frame_context import DisplaySourceContext

TransferKind = Literal["srgb", "pq", "hlg", "linear", "unknown"]
PrimariesKind = Literal["bt709", "bt2020", "unknown"]
MetadataConfidence = Literal["backend", "compositor", "user", "heuristic", "fallback", "unknown"]


@dataclass(frozen=True)
class ColorContext:
    transfer: TransferKind
    primaries: PrimariesKind
    max_nits: float
    source: str
    confidence: MetadataConfidence
    display_referred: bool
    skip_display_gamut_adaptation: bool
    gamut_matrix: np.ndarray | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "transfer": self.transfer,
            "primaries": self.primaries,
            "max_nits": self.max_nits,
            "source": self.source,
            "confidence": self.confidence,
            "display_referred": self.display_referred,
            "skip_display_gamut_adaptation": self.skip_display_gamut_adaptation,
            "gamut_matrix_available": self.gamut_matrix is not None,
        }


def _normalize_transfer(value: object) -> TransferKind:
    normalized = str(value or "unknown").strip().lower()
    if normalized in {"srgb", "pq", "hlg", "linear", "unknown"}:
        return normalized  # type: ignore[return-value]
    return "unknown"


def _normalize_primaries(value: object) -> PrimariesKind:
    normalized = str(value or "unknown").strip().lower()
    if normalized in {"bt709", "bt2020", "unknown"}:
        return normalized  # type: ignore[return-value]
    return "unknown"


def _metadata_confidence(metadata: CaptureMetadata) -> MetadataConfidence:
    source = str(metadata.source or "").strip().lower()
    if "kwin screenshot2 metadata" in source or source == "backend":
        return "backend"
    if source in {"user preset", "user"}:
        return "user"
    if source in {"plasma auto", "session fallback"}:
        return "compositor"
    if source in {"kwin display-referred"}:
        return "heuristic"
    if source:
        return "fallback"
    return "unknown"


def build_color_context(
    *,
    metadata: CaptureMetadata,
    display_source: DisplaySourceContext | None = None,
    skip_display_gamut_adaptation: bool | None = None,
) -> ColorContext:
    skip = (
        bool(skip_display_gamut_adaptation)
        if skip_display_gamut_adaptation is not None
        else bool(metadata.skip_display_gamut_adaptation)
    )
    display_referred = "display-referred" in str(metadata.source or "").lower()
    matrix = None if skip else get_gamut_adaptation_matrix()
    confidence = _metadata_confidence(metadata)
    if (
        display_source is not None
        and display_source.source_confidence == "unknown"
        and confidence == "unknown"
    ):
        confidence = "fallback"
    return ColorContext(
        transfer=_normalize_transfer(metadata.transfer),
        primaries=_normalize_primaries(metadata.primaries),
        max_nits=float(metadata.max_nits),
        source=str(metadata.source or "unknown"),
        confidence=confidence,
        display_referred=display_referred,
        skip_display_gamut_adaptation=skip,
        gamut_matrix=matrix,
    )


def color_context_from_display_source(
    display_source: DisplaySourceContext,
    *,
    skip_display_gamut_adaptation: bool | None = None,
) -> ColorContext:
    return build_color_context(
        metadata=display_source.hdr_metadata,
        display_source=display_source,
        skip_display_gamut_adaptation=skip_display_gamut_adaptation,
    )
