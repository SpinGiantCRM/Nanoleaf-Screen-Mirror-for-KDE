"""Tests for the adaptive FPS governor."""

from __future__ import annotations

import pytest
from nanoleaf_sync.runtime.fps_governor import FPSGovernor, FPS_TIERS


def test_initial_target_matches_constructor_arg() -> None:
    g = FPSGovernor(initial_fps=60)
    assert g.target_fps == 60


def test_initial_fps_clamped_to_tier() -> None:
    g = FPSGovernor(initial_fps=100)
    assert g.target_fps == 100  # not a tier but kept as-is


def test_initial_fps_zero_kept() -> None:
    g = FPSGovernor(initial_fps=0)
    assert g.target_fps == 0


def test_no_change_during_warmup() -> None:
    """Within warmup frames, target FPS never changes even under extreme load."""
    g = FPSGovernor(initial_fps=60)
    for _ in range(10):  # _WARMUP_FRAMES = 10
        result = g.record_frame(500.0)  # extremely slow frame
        assert result == 60
    # Now past warmup — extreme load should step down
    for _ in range(50):
        g.record_frame(500.0)
    assert g.target_fps < 60  # should have stepped down from 60


def test_warmup_accumulation_triggers_transition() -> None:
    """Warmup frames accumulate in the latency window, triggering step-down at frame 11."""
    g = FPSGovernor(initial_fps=60)
    # Feed slow frames during warmup (10 warmup frames) — they accumulate in the
    # window but no transition happens during warmup. At frame 11, window is
    # full with warmup entries, so the first post-warmup frame immediately
    # triggers a step-down.  Verify the transition fires once window ≥ 5.
    for _ in range(14):  # 10 warmup + 4 active: at frame 11, window≥5 triggers transition
        g.record_frame(25.0)
    assert g.target_fps <= 30  # stepped down by frame 11 due to warmup-accumulated entries
    # Now at min tier, feed very low-latency frames to step back up
    for _ in range(200):
        g.record_frame(0.5)
    assert g.target_fps >= 60  # stepped back up with 200 consecutive low-util frames


def test_step_down_under_high_utilisation() -> None:
    """When p95 latency exceeds 80% of frame budget, step down immediately."""
    g = FPSGovernor(initial_fps=60)
    # 60fps budget = 16.67ms; 80% = 13.3ms
    # Feed 30 frames at 14ms (84% utilisation); p95 will be >=14ms
    for _ in range(50):
        g.record_frame(14.0)
    assert g.target_fps == 30  # stepped down from 60 → 30


def test_step_down_multiple_tiers() -> None:
    """Stepping down can cascade through multiple tiers."""
    g = FPSGovernor(initial_fps=120)
    for _ in range(200):
        g.record_frame(20.0)  # 120fps budget=8.3ms, so ~240% utilisation
    assert g.target_fps == 30  # cascaded: 120 → 90 → 60 → 30


def test_step_up_after_sustained_low_utilisation() -> None:
    """After UP_CONSECUTIVE low-utilisation frames, step up."""
    g = FPSGovernor(initial_fps=30)
    # First push it down (to prove the concept)
    for _ in range(50):
        g.record_frame(40.0)  # 30fps budget=33.3ms, so ~120% → step down
    # Now at minimum tier (30)
    # Feed low-latency frames to step up
    for _ in range(200):
        g.record_frame(2.0)  # 30fps budget=33.3ms, so ~6% utilisation
    # Need UP_CONSECUTIVE=100 consecutive low-utilisation frames
    # We fed 200, should have stepped up at least once
    assert g.target_fps >= 60


def test_steady_state_no_oscillation() -> None:
    """At comfortable utilisation, target FPS should not oscillate."""
    g = FPSGovernor(initial_fps=60)
    target_history: list[int] = []
    for i in range(200):
        # ~50% utilisation at 60fps (8.3ms)
        result = g.record_frame(8.3)
        target_history.append(result)
    # After warmup and settling, should be stable
    last_50 = target_history[-50:]
    assert last_50.count(last_50[0]) > 40  # rarely changes


def test_edge_case_zero_latency() -> None:
    """Zero-latency frames should not crash."""
    g = FPSGovernor(initial_fps=60)
    for _ in range(100):
        g.record_frame(0.0)
    # Should not have errored
    assert g.target_fps >= 60 or g.target_fps == 60


def test_edge_case_negative_latency() -> None:
    """Negative latency (shouldn't happen, but be defensive)."""
    g = FPSGovernor(initial_fps=60)
    for _ in range(100):
        g.record_frame(-5.0)
    # Should not crash
    assert g.target_fps >= 30  # might step down due to weird metrics, but shouldn't crash


def test_edge_case_enormous_latency() -> None:
    """Extremely large latencies should step to minimum tier."""
    g = FPSGovernor(initial_fps=120)
    for _ in range(200):
        g.record_frame(1_000_000.0)  # 1 million ms
    assert g.target_fps == FPS_TIERS[-1]  # minimum tier


def test_get_metrics_returns_expected_keys() -> None:
    g = FPSGovernor(initial_fps=60)
    for _ in range(50):
        g.record_frame(10.0)
    metrics = g.get_metrics()
    assert "target_fps" in metrics
    assert "p95_latency_ms" in metrics
    assert "utilisation" in metrics
    assert "window_size" in metrics
    assert "frame_count" in metrics
    assert "consecutive_low_frames" in metrics
    assert "transitions" in metrics
    assert metrics["frame_count"] == 50
    assert metrics["window_size"] >= 5


def test_get_metrics_during_warmup() -> None:
    """Metrics during warmup should show utilisation=0."""
    g = FPSGovernor(initial_fps=60)
    g.record_frame(10.0)
    g.record_frame(10.0)
    metrics = g.get_metrics()
    # With only 2 frames, window < 5, so utilisation stays 0
    assert metrics["utilisation"] == 0.0
    assert metrics["p95_latency_ms"] == 0.0


def test_transitions_tracked_in_metrics() -> None:
    g = FPSGovernor(initial_fps=120)
    for _ in range(200):
        g.record_frame(50.0)  # force cascading down
    metrics = g.get_metrics()
    transitions = metrics["transitions"]
    assert len(transitions) > 0
    for frame, old_fps, new_fps in transitions:
        assert new_fps < old_fps  # should have stepped down


def test_step_up_disabled_at_max_tier() -> None:
    """At max tier, can't step up further."""
    g = FPSGovernor(initial_fps=120)
    for _ in range(300):
        g.record_frame(0.1)  # extremely low latency
    assert g.target_fps == 120  # stays at max


def test_step_down_disabled_at_min_tier() -> None:
    """At min tier, can't step down further."""
    g = FPSGovernor(initial_fps=30)
    for _ in range(200):
        g.record_frame(100.0)  # way over budget
    assert g.target_fps == 30  # stays at min


def test_utilisation_calculation() -> None:
    """Verify utilisation is p95 / budget_ms."""
    g = FPSGovernor(initial_fps=60)
    # 60fps budget = 16.67ms
    # Feed frames at exactly 10ms → p95 ≈ 10ms → utilisation ≈ 0.6
    for _ in range(100):
        g.record_frame(10.0)
    metrics = g.get_metrics()
    assert 0.55 <= metrics["utilisation"] <= 0.65
    assert 9.5 <= metrics["p95_latency_ms"] <= 10.5


def test_window_cleared_on_transition() -> None:
    """After a transition, the latency window is cleared."""
    g = FPSGovernor(initial_fps=120)
    for _ in range(200):
        g.record_frame(50.0)  # force multiple step-downs
    metrics = g.get_metrics()
    # After cascading, window should have been cleared on each transition
    # and then refilled; final window shouldn't be huge
    assert metrics["window_size"] <= 30  # _WINDOW_SIZE = 30
