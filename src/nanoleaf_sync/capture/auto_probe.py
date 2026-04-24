from __future__ import annotations

import statistics
from typing import Sequence, cast

from nanoleaf_sync.capture.factory import create_capture_backend
from nanoleaf_sync.capture.interfaces import CaptureBackend
from nanoleaf_sync.capture.probe_models import (
    BackendFactory,
    CandidateProbeResult,
    ProbeConfig,
    ProbeError,
    ProbeErrorKind,
    ProbeResult,
    ProbeStage,
)
from nanoleaf_sync.capture.probe_timing import call_with_timeout, monotonic_s


def _default_backend_factory(candidate: str, width: int, height: int) -> CaptureBackend:
    return create_capture_backend(
        width=width,
        height=height,
        use_mock_capture=False,
        prefer_backend=candidate,
    )


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


def _record_error(stats: CandidateProbeResult, error: ProbeError) -> None:
    if error.message not in {item.message for item in stats.errors}:
        stats.errors.append(error)


def _build_probe_error(stage: str, exc: Exception) -> ProbeError:
    stage_name = cast(ProbeStage, stage)
    message = str(exc).strip() or exc.__class__.__name__
    if isinstance(exc, TimeoutError):
        return ProbeError(kind="timeout", stage=stage_name, message=message)
    if stage == "instantiate":
        kind = "backend-init"
    elif stage == "close":
        kind = "backend-close"
    elif stage in {"warmup", "capture"}:
        kind = "capture-failed"
    else:
        kind = "unknown"
    kind_name = cast(ProbeErrorKind, kind)
    return ProbeError(kind=kind_name, stage=stage_name, message=message)


def probe_backends(
    width: int,
    height: int,
    candidates: Sequence[str],
    probe_config: ProbeConfig,
) -> ProbeResult:
    """Probe candidate capture backends and rank by reliability then latency."""

    iterations = max(3, min(5, int(probe_config.measure_iterations)))
    factory = cast(BackendFactory, probe_config.backend_factory or _default_backend_factory)

    started = monotonic_s()
    deadline = started + max(0.1, probe_config.global_timeout_s)
    timed_out = False
    results: list[CandidateProbeResult] = []

    for candidate in candidates:
        if monotonic_s() >= deadline:
            timed_out = True
            break

        stats = CandidateProbeResult(candidate=candidate)
        backend: CaptureBackend | None = None

        try:
            remaining = max(0.0, deadline - monotonic_s())
            backend = call_with_timeout(
                lambda: factory(candidate, width, height),
                min(probe_config.instantiate_timeout_s, remaining),
                op_name=f"{candidate} instantiate",
            )

            try:
                remaining = max(0.0, deadline - monotonic_s())
                stats.attempted_captures += 1
                warmup_start = monotonic_s()
                call_with_timeout(
                    lambda: backend.capture(),
                    min(probe_config.warmup_timeout_s, remaining),
                    op_name=f"{candidate} warmup capture",
                )
                stats.success_count += 1
                stats.latencies_ms.append((monotonic_s() - warmup_start) * 1000.0)
            except Exception as exc:  # noqa: BLE001 - diagnostics collection
                _record_error(stats, _build_probe_error("warmup", exc))

            for _ in range(iterations):
                if monotonic_s() >= deadline:
                    timed_out = True
                    break
                stats.attempted_captures += 1
                capture_start = monotonic_s()
                try:
                    remaining = max(0.0, deadline - monotonic_s())
                    call_with_timeout(
                        lambda: backend.capture(),
                        min(probe_config.capture_timeout_s, remaining),
                        op_name=f"{candidate} capture",
                    )
                    stats.success_count += 1
                    stats.latencies_ms.append((monotonic_s() - capture_start) * 1000.0)
                except Exception as exc:  # noqa: BLE001 - diagnostics collection
                    stats.failure_count += 1
                    _record_error(stats, _build_probe_error("capture", exc))

        except Exception as exc:  # noqa: BLE001 - diagnostics collection
            _record_error(stats, _build_probe_error("instantiate", exc))
        finally:
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
                        remaining = max(0.0, deadline - monotonic_s())
                        call_with_timeout(
                            close_fn,
                            min(probe_config.close_timeout_s, remaining),
                            op_name=f"{candidate} close",
                        )
                    except Exception as exc:  # noqa: BLE001 - diagnostics collection
                        _record_error(stats, _build_probe_error("close", exc))

    ranked = sorted(
        results,
        key=lambda item: (
            not item.qualified,
            float("inf") if item.median_ms is None else round(item.median_ms),
            item.candidate,
        ),
    )

    selected = ranked[0].candidate if ranked and ranked[0].qualified else None
    return ProbeResult(
        selected_backend=selected,
        candidates=ranked,
        started_monotonic_s=started,
        elapsed_s=monotonic_s() - started,
        timed_out=timed_out,
    )
