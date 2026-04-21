from __future__ import annotations

from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class LatencyMeasurement:
    sample_count: int
    capture_interval_median_ms: float
    capture_interval_p95_ms: float
    pipeline_median_ms: float
    pipeline_p95_ms: float
    pipeline_jitter_ms: float


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
    """Collects runtime timing samples for capture cadence + pipeline latency."""

    def __init__(self, *, max_samples: int = 240) -> None:
        self._max_samples = max(8, int(max_samples))
        self._last_capture_ts: float | None = None
        self._capture_intervals_ms: list[float] = []
        self._pipeline_ms: list[float] = []

    def add_sample(
        self,
        *,
        capture_ts: float,
        process_done_ts: float,
        send_done_ts: float,
    ) -> bool:
        capture = float(capture_ts)
        process_done = float(process_done_ts)
        send_done = float(send_done_ts)
        if capture <= 0.0 or process_done < capture or send_done < process_done:
            return False

        if self._last_capture_ts is not None and capture >= self._last_capture_ts:
            capture_interval = (capture - self._last_capture_ts) * 1000.0
            if capture_interval > 0.0:
                self._capture_intervals_ms.append(capture_interval)
        self._last_capture_ts = capture

        pipeline_ms = (send_done - capture) * 1000.0
        if pipeline_ms > 0.0:
            self._pipeline_ms.append(pipeline_ms)

        if len(self._capture_intervals_ms) > self._max_samples:
            self._capture_intervals_ms = self._capture_intervals_ms[-self._max_samples :]
        if len(self._pipeline_ms) > self._max_samples:
            self._pipeline_ms = self._pipeline_ms[-self._max_samples :]
        return True

    def measurement(self) -> LatencyMeasurement | None:
        if not self._pipeline_ms:
            return None
        pipeline = list(self._pipeline_ms)
        cadence = list(self._capture_intervals_ms)
        return LatencyMeasurement(
            sample_count=len(pipeline),
            capture_interval_median_ms=median(cadence) if cadence else 0.0,
            capture_interval_p95_ms=_percentile(cadence, 0.95) if cadence else 0.0,
            pipeline_median_ms=median(pipeline),
            pipeline_p95_ms=_percentile(pipeline, 0.95),
            pipeline_jitter_ms=max(pipeline) - min(pipeline) if len(pipeline) > 1 else 0.0,
        )

