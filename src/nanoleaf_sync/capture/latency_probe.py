from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import median


STAGE_CAPTURE_WAIT = "capture_wait_ms"
STAGE_CAPTURE_CALL = "capture_call_ms"
STAGE_RUNTIME_CAPTURE_CALL = "runtime_capture_call_ms"
STAGE_CAPTURE_WORKER_LOOP_GAP = "capture_worker_loop_gap_ms"
STAGE_CAPTURE_SUCCESS_INTERVAL = "capture_success_interval_ms"
STAGE_FRAME_HANDOFF_WAIT = "frame_handoff_wait_ms"
STAGE_FRAME_AVAILABLE_WAIT = "frame_available_wait_ms"
STAGE_PENDING_FRAME_AGE = "pending_frame_age_ms"
STAGE_PACING_WAIT = "pacing_wait_ms"
STAGE_IDLE_WAIT = "idle_wait_ms"
STAGE_RUNTIME_IDLE_WAIT = "runtime_idle_wait_ms"
STAGE_FRAME_PROCESSING = "frame_processing_ms"
STAGE_FRAME_CONVERT = "frame_convert_ms"
STAGE_ZONE_SAMPLING = "zone_sampling_ms"
STAGE_COLOUR_PROCESSING = "colour_processing_ms"
STAGE_SMOOTHING = "smoothing_ms"
STAGE_LED_CALIBRATION = "led_calibration_ms"
STAGE_OUTPUT_PREPARE = "output_prepare_ms"
STAGE_ACTUAL_WORK = "actual_work_ms"
STAGE_HID_WRITE = "hid_write_ms"
STAGE_HID_FRAME_BUILD = "hid_frame_build_ms"
STAGE_HID_DEVICE_WRITE = "hid_device_write_ms"
STAGE_HID_FLUSH_OR_WAIT = "hid_flush_or_wait_ms"
STAGE_LOOP_GAP = "loop_gap_ms"
STAGE_INFERRED_UNATTRIBUTED_GAP = "inferred_unattributed_gap_ms"
STAGE_END_TO_END_LIVE = "end_to_end_live_ms"

ALL_STAGE_NAMES = (
    STAGE_LOOP_GAP,
    STAGE_PACING_WAIT,
    STAGE_IDLE_WAIT,
    STAGE_RUNTIME_IDLE_WAIT,
    STAGE_CAPTURE_WAIT,
    STAGE_CAPTURE_CALL,
    STAGE_RUNTIME_CAPTURE_CALL,
    STAGE_CAPTURE_WORKER_LOOP_GAP,
    STAGE_CAPTURE_SUCCESS_INTERVAL,
    STAGE_FRAME_HANDOFF_WAIT,
    STAGE_FRAME_AVAILABLE_WAIT,
    STAGE_PENDING_FRAME_AGE,
    STAGE_FRAME_PROCESSING,
    STAGE_FRAME_CONVERT,
    STAGE_ZONE_SAMPLING,
    STAGE_COLOUR_PROCESSING,
    STAGE_SMOOTHING,
    STAGE_LED_CALIBRATION,
    STAGE_OUTPUT_PREPARE,
    STAGE_ACTUAL_WORK,
    STAGE_HID_WRITE,
    STAGE_HID_FRAME_BUILD,
    STAGE_HID_DEVICE_WRITE,
    STAGE_HID_FLUSH_OR_WAIT,
    STAGE_END_TO_END_LIVE,
    STAGE_INFERRED_UNATTRIBUTED_GAP,
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
    target_fps: float
    fps_cap: float
    fps_cap_reason: str
    effective_output_fps: float
    stages: dict[str, StageStats]
    counters: dict[str, int]
    flags: dict[str, bool]
    labels: dict[str, str]


@dataclass(frozen=True)
class FrameTimingSample:
    stage_ms: dict[str, float | None]
    target_fps: float | None = None
    fps_cap: float | None = None
    fps_cap_reason: str = ""
    dropped_or_skipped_frames_delta: int = 0
    counters_delta: dict[str, int] | None = None
    flags: dict[str, bool] | None = None
    labels: dict[str, str] | None = None


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
        self._counters: dict[str, int] = {}
        self._flags: dict[str, bool] = {}
        self._labels: dict[str, str] = {}
        self._target_fps = 0.0
        self._fps_cap = 0.0
        self._fps_cap_reason = ""

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
        if isinstance(sample.counters_delta, dict):
            for key, delta in sample.counters_delta.items():
                if int(delta) == 0:
                    continue
                self._counters[str(key)] = self._counters.get(str(key), 0) + int(delta)
        if isinstance(sample.flags, dict):
            for key, value in sample.flags.items():
                self._flags[str(key)] = bool(value)
        if isinstance(sample.labels, dict):
            for key, value in sample.labels.items():
                text = str(value or "").strip()
                if text:
                    self._labels[str(key)] = text
        if sample.target_fps is not None:
            self._target_fps = max(0.0, float(sample.target_fps))
        if sample.fps_cap is not None:
            self._fps_cap = max(0.0, float(sample.fps_cap))
        self._fps_cap_reason = str(sample.fps_cap_reason or self._fps_cap_reason)
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
            target_fps=float(self._target_fps),
            fps_cap=float(self._fps_cap),
            fps_cap_reason=str(self._fps_cap_reason),
            effective_output_fps=effective_output_fps,
            stages=stage_stats,
            counters=dict(self._counters),
            flags=dict(self._flags),
            labels=dict(self._labels),
        )

    def stage_values(self, stage_name: str) -> list[float]:
        return list(self._samples.get(stage_name, ()))
