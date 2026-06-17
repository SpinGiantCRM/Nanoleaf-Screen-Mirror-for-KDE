"""Tests for auto_probe.py pure functions."""

from __future__ import annotations


from nanoleaf_sync.capture.probe_models import CandidateProbeResult, ProbeError
from nanoleaf_sync.capture.auto_probe import (
    _compute_p95,
    _mark_stats,
    _build_probe_error,
    _record_error,
)


# ---------------------------------------------------------------------------
# _compute_p95
# ---------------------------------------------------------------------------


def test_compute_p95_multiple_values() -> None:
    values = list(range(1, 101))  # 1 to 100
    p95 = _compute_p95(values)
    # p95 of 1-100 should be approximately 95
    assert 90 <= p95 <= 100


def test_compute_p95_single_value() -> None:
    assert _compute_p95([42.0]) == 42.0


def test_compute_p95_two_values() -> None:
    result = _compute_p95([10.0, 20.0])
    assert 10.0 <= result <= 20.0


# ---------------------------------------------------------------------------
# _mark_stats
# ---------------------------------------------------------------------------


def test_mark_stats_with_latencies() -> None:
    stats = CandidateProbeResult(
        candidate="test",
        attempted_captures=10,
        success_count=10,
        latencies_ms=[5.0, 6.0, 7.0, 8.0, 9.0, 5.5, 6.5, 7.5, 8.5, 9.5],
    )
    _mark_stats(stats, min_success_ratio=0.5)
    assert stats.median_ms is not None
    assert stats.p95_ms is not None
    assert stats.jitter_ms is not None
    assert stats.jitter_ms >= 0
    assert stats.qualified is True
    assert stats.status == "tested"


def test_mark_stats_qualified_false() -> None:
    stats = CandidateProbeResult(
        candidate="test",
        attempted_captures=10,
        success_count=3,  # 30% < 50%
        latencies_ms=[5.0, 6.0, 7.0],
    )
    _mark_stats(stats, min_success_ratio=0.5)
    assert stats.qualified is False


def test_mark_stats_no_latencies() -> None:
    stats = CandidateProbeResult(
        candidate="test",
        attempted_captures=5,
        success_count=0,
        latencies_ms=[],
    )
    _mark_stats(stats, min_success_ratio=0.5)
    assert stats.median_ms is None
    # No successes, no errors → status remains "skipped" (untested fallback)
    assert stats.status == "skipped"


def test_mark_stats_untested_with_success() -> None:
    stats = CandidateProbeResult(
        candidate="test",
        status="untested",
        attempted_captures=5,
        success_count=3,
        latencies_ms=[5.0, 6.0, 7.0],
    )
    _mark_stats(stats, min_success_ratio=0.5)
    assert stats.status == "tested"


def test_mark_stats_untested_without_success() -> None:
    stats = CandidateProbeResult(
        candidate="test",
        status="untested",
        attempted_captures=5,
        success_count=0,
        latencies_ms=[],
        errors=[ProbeError(kind="capture-failed", stage="capture", message="fail")],
    )
    _mark_stats(stats, min_success_ratio=0.5)
    assert stats.status == "failed"


def test_mark_stats_jitter_single_value() -> None:
    stats = CandidateProbeResult(
        candidate="test",
        attempted_captures=1,
        success_count=1,
        latencies_ms=[7.0],
    )
    _mark_stats(stats, min_success_ratio=0.5)
    assert stats.jitter_ms == 0.0


# ---------------------------------------------------------------------------
# _build_probe_error
# ---------------------------------------------------------------------------


def test_build_probe_error_timeout() -> None:
    error = _build_probe_error("capture", TimeoutError("timed out"))
    assert error.kind == "timeout"
    assert error.stage == "capture"
    assert "timed out" in error.message


def test_build_probe_error_backend_init() -> None:
    error = _build_probe_error("instantiate", RuntimeError("init failed"))
    assert error.kind == "backend-init"
    assert error.stage == "instantiate"


def test_build_probe_error_backend_close() -> None:
    error = _build_probe_error("close", RuntimeError("close failed"))
    assert error.kind == "backend-close"
    assert error.stage == "close"


def test_build_probe_error_capture_failed() -> None:
    error = _build_probe_error("capture", RuntimeError("capture error"))
    assert error.kind == "capture-failed"


def test_build_probe_error_warmup() -> None:
    error = _build_probe_error("warmup", RuntimeError("warmup error"))
    assert error.kind == "capture-failed"


def test_build_probe_error_unknown_stage() -> None:
    error = _build_probe_error("unknown_stage", RuntimeError("weird"))
    assert error.kind == "unknown"


def test_build_probe_error_empty_message() -> None:
    error = _build_probe_error("capture", ValueError(""))
    # Falls back to class name
    assert "ValueError" in error.message


# ---------------------------------------------------------------------------
# _record_error
# ---------------------------------------------------------------------------


def test_record_error_new() -> None:
    stats = CandidateProbeResult(candidate="test")
    error = ProbeError(kind="capture-failed", stage="capture", message="first")
    _record_error(stats, error)
    assert len(stats.errors) == 1
    assert stats.errors[0].message == "first"


def test_record_error_dedup() -> None:
    stats = CandidateProbeResult(candidate="test")
    error1 = ProbeError(kind="capture-failed", stage="capture", message="same")
    error2 = ProbeError(kind="capture-failed", stage="capture", message="same")
    _record_error(stats, error1)
    _record_error(stats, error2)
    assert len(stats.errors) == 1


def test_record_error_different_messages() -> None:
    stats = CandidateProbeResult(candidate="test")
    error1 = ProbeError(kind="capture-failed", stage="capture", message="first")
    error2 = ProbeError(kind="capture-failed", stage="capture", message="second")
    _record_error(stats, error1)
    _record_error(stats, error2)
    assert len(stats.errors) == 2
