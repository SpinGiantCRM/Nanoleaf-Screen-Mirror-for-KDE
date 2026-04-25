from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import median
from typing import Iterable


STAGE_CAPTURE_WAIT = "capture_wait_ms"
STAGE_CAPTURE_READ = "capture_read_ms"
STAGE_FRAME_CONVERT = "frame_convert_ms"
STAGE_ZONE_SAMPLING = "zone_sampling_ms"
STAGE_COLOUR_PROCESSING = "colour_processing_ms"
STAGE_SMOOTHING = "smoothing_ms"
STAGE_HID_WRITE = "hid_write_ms"
STAGE_FRAME_TOTAL = "frame_total_ms"
STAGE_LOOP_GAP = "loop_gap_ms"

ALL_STAGE_NAMES = (
    STAGE_CAPTURE_WAIT,
    STAGE_CAPTURE_READ,
    STAGE_FRAME_CONVERT,
    STAGE_ZONE_SAMPLING,
    STAGE_COLOUR_PROCESSING,
    STAGE_SMOOTHING,
    STAGE_HID_WRITE,
    STAGE_FRAME_TOTAL,
    STAGE_LOOP_GAP,
)


@dataclass(frozen=True)
class StageStats:
    sample_count: int
    median_ms: float
    p95_ms: float
    max_ms: float
    available: bool


@dataclass(frozen=True)
class LatencyMeasurement:
    live_mirroring_only: bool
    dropped_or_skipped_frames: int
    effective_output_fps: float
    stages: dict[str, StageStats]


@dataclass(frozen=True)
class FrameTimingSample:
    stage_ms: dict[str, float | None]
    dropped_or_skipped_frames_delta: int = 0


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return float(ordered[lower])
    frac = rank - lower
    return float(ordered[lower] + ((ordered[upper] - ordered[lower]) * frac))


class LatencyProbe:
    """Collects rolling live-mirroring timing samples for each runtime stage."""

    def __init__(self, *, max_samples: int = 240) -> None:
        self._max_samples = max(8, int(max_samples))
        self._samples: dict[str, deque[float]] = {
            stage: deque(maxlen=self._max_samples) for stage in ALL_STAGE_NAMES
        }
        self._dropped_or_skipped_frames = 0

    def add_stage_sample(self, sample: FrameTimingSample) -> bool:
        seen_any = False
        for stage in ALL_STAGE_NAMES:
            value = sample.stage_ms.get(stage)
            if value is None:
                continue
            value_f = float(value)
            if value_f < 0.0:
                continue
            self._samples[stage].append(value_f)
            seen_any = True

        self._dropped_or_skipped_frames += max(0, int(sample.dropped_or_skipped_frames_delta))
        return seen_any

    def measurement(self) -> LatencyMeasurement | None:
        if not any(self._samples[stage] for stage in ALL_STAGE_NAMES):
            return None

        stage_stats: dict[str, StageStats] = {}
        for stage in ALL_STAGE_NAMES:
            values = list(self._samples[stage])
            if not values:
                stage_stats[stage] = StageStats(
                    sample_count=0,
                    median_ms=0.0,
                    p95_ms=0.0,
                    max_ms=0.0,
                    available=False,
                )
                continue
            stage_stats[stage] = StageStats(
                sample_count=len(values),
                median_ms=median(values),
                p95_ms=_percentile(values, 0.95),
                max_ms=max(values),
                available=True,
            )

        loop_gap = stage_stats.get(STAGE_LOOP_GAP)
        effective_output_fps = 0.0
        if loop_gap and loop_gap.available and loop_gap.median_ms > 0.0:
            effective_output_fps = 1000.0 / loop_gap.median_ms

        return LatencyMeasurement(
            live_mirroring_only=True,
            dropped_or_skipped_frames=int(self._dropped_or_skipped_frames),
            effective_output_fps=effective_output_fps,
            stages=stage_stats,
        )

    def stage_values(self, stage_name: str) -> list[float]:
        return list(self._samples.get(stage_name, ()))
