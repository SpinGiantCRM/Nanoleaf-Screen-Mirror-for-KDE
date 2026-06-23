from __future__ import annotations

from dataclasses import dataclass

from nanoleaf_sync.color.capture_metadata import CaptureMetadata


def _metadata_key(metadata: CaptureMetadata) -> str:
    return "|".join(
        (
            str(metadata.confidence),
            str(metadata.source),
            str(metadata.transfer),
            str(metadata.primaries),
            str(bool(metadata.skip_display_gamut_adaptation)),
            str(bool(metadata.capture_primaries_converted)),
        )
    )


@dataclass
class MetadataHysteresisTracker:
    frames_required: int = 3
    stable: CaptureMetadata | None = None
    candidate: CaptureMetadata | None = None
    candidate_frames: int = 0
    transitions: int = 0

    def update(self, observed: CaptureMetadata) -> CaptureMetadata:
        if self.stable is None:
            self.stable = observed
            return observed
        observed_key = _metadata_key(observed)
        stable_key = _metadata_key(self.stable)
        if observed_key == stable_key:
            if self.candidate_frames > 0:
                self.candidate_frames = max(0, self.candidate_frames - 1)
            if self.candidate_frames == 0:
                self.candidate = None
            return self.stable
        if self.candidate is not None and _metadata_key(self.candidate) == observed_key:
            self.candidate_frames += 1
        else:
            self.candidate = observed
            self.candidate_frames = 1
        if self.candidate_frames >= max(1, int(self.frames_required)):
            self.stable = self.candidate
            self.candidate = None
            self.candidate_frames = 0
            self.transitions += 1
            return self.stable
        return self.stable

    def reset(self) -> None:
        self.stable = None
        self.candidate = None
        self.candidate_frames = 0
