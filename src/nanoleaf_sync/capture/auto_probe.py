from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
import statistics
import time
from typing import Callable, Sequence

from nanoleaf_sync.capture.factory import create_capture_backend
from nanoleaf_sync.capture.interfaces import CaptureBackend


BackendFactory = Callable[[str, int, int], CaptureBackend]


@dataclass(frozen=True)
class ProbeConfig:
    measure_iterations: int = 5
    min_success_ratio: float = 0.6
    global_timeout_s: float = 8.0
    instantiate_timeout_s: float = 2.0
    warmup_timeout_s: float = 2.0
    capture_timeout_s: float = 1.0
    close_timeout_s: float = 0.5
    backend_factory: BackendFactory | None = None


@dataclass
class CandidateProbeResult:
    candidate: str
    attempted_captures: int = 0
    success_count: int = 0
    failure_count: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    error_messages: list[str] = field(default_factory=list)
    median_ms: float | None = None
    p95_ms: float | None = None
    qualified: bool = False


@dataclass
class ProbeResult:
    selected_backend: str | None
    candidates: list[CandidateProbeResult]
    started_monotonic_s: float
    elapsed_s: float
    timed_out: bool = False


def _default_backend_factory(candidate: str, width: int, height: int) -> CaptureBackend:
    return create_capture_backend(
        width=width,
        height=height,
        use_mock_capture=False,
        prefer_backend=candidate,
    )


def _call_with_timeout(func: Callable[[], object], timeout_s: float) -> object:
    if timeout_s <= 0.0:
        raise TimeoutError("operation timeout must be > 0 seconds")

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="capture-probe") as pool:
        future = pool.submit(func)
        try:
            return future.result(timeout=timeout_s)
        except FutureTimeoutError as exc:
            raise TimeoutError(f"operation timed out after {timeout_s:.2f}s") from exc


def _compute_p95(values: Sequence[float]) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[94]


def _mark_stats(stats: CandidateProbeResult, min_success_ratio: float) -> None:
    if stats.latencies_ms:
        stats.median_ms = statistics.median(stats.latencies_ms)
        stats.p95_ms = _compute_p95(stats.latencies_ms)

    total = stats.attempted_captures
    ratio = (stats.success_count / total) if total > 0 else 0.0
    stats.qualified = ratio >= min_success_ratio


def _record_error(stats: CandidateProbeResult, exc: Exception) -> None:
    message = str(exc).strip() or exc.__class__.__name__
    if message not in stats.error_messages:
        stats.error_messages.append(message)


def probe_backends(
    width: int,
    height: int,
    candidates: Sequence[str],
    probe_config: ProbeConfig,
) -> ProbeResult:
    """Probe candidate capture backends and rank by reliability then latency."""

    iterations = max(3, min(5, int(probe_config.measure_iterations)))
    factory = probe_config.backend_factory or _default_backend_factory

    started = time.monotonic()
    deadline = started + max(0.1, probe_config.global_timeout_s)
    timed_out = False
    results: list[CandidateProbeResult] = []

    for candidate in candidates:
        if time.monotonic() >= deadline:
            timed_out = True
            break

        stats = CandidateProbeResult(candidate=candidate)
        backend: CaptureBackend | None = None

        try:
            remaining = max(0.0, deadline - time.monotonic())
            backend = _call_with_timeout(
                lambda: factory(candidate, width, height),
                min(probe_config.instantiate_timeout_s, remaining),
            )

            # Warm-up capture.
            remaining = max(0.0, deadline - time.monotonic())
            stats.attempted_captures += 1
            warmup_start = time.monotonic()
            _call_with_timeout(
                lambda: backend.capture(),
                min(probe_config.warmup_timeout_s, remaining),
            )
            stats.success_count += 1
            stats.latencies_ms.append((time.monotonic() - warmup_start) * 1000.0)

            # Measured captures.
            for _ in range(iterations):
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                stats.attempted_captures += 1
                capture_start = time.monotonic()
                try:
                    remaining = max(0.0, deadline - time.monotonic())
                    _call_with_timeout(
                        lambda: backend.capture(),
                        min(probe_config.capture_timeout_s, remaining),
                    )
                    stats.success_count += 1
                    stats.latencies_ms.append((time.monotonic() - capture_start) * 1000.0)
                except Exception as exc:  # noqa: BLE001 - diagnostics collection
                    stats.failure_count += 1
                    _record_error(stats, exc)

        except Exception as exc:  # noqa: BLE001 - diagnostics collection
            _record_error(stats, exc)
        finally:
            # Keep count coherent if startup/warmup failed.
            stats.failure_count = max(
                stats.failure_count,
                stats.attempted_captures - stats.success_count,
            )
            _mark_stats(stats, probe_config.min_success_ratio)
            results.append(stats)

            if backend is not None:
                close_fn = getattr(backend, "close", None)
                if callable(close_fn):
                    try:
                        remaining = max(0.0, deadline - time.monotonic())
                        _call_with_timeout(
                            close_fn,
                            min(probe_config.close_timeout_s, remaining),
                        )
                    except Exception as exc:  # noqa: BLE001 - diagnostics collection
                        _record_error(stats, exc)

    ranked = sorted(
        results,
        key=lambda item: (
            not item.qualified,
            float("inf") if item.median_ms is None else item.median_ms,
            item.candidate,
        ),
    )

    selected = ranked[0].candidate if ranked and ranked[0].qualified else None
    return ProbeResult(
        selected_backend=selected,
        candidates=ranked,
        started_monotonic_s=started,
        elapsed_s=time.monotonic() - started,
        timed_out=timed_out,
    )
