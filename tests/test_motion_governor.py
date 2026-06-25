from __future__ import annotations

from nanoleaf_sync.runtime.fps_governor import FPSGovernor


def _feed_static(g: FPSGovernor, frames: int) -> None:
    for _ in range(frames):
        g.signal_motion(0.0)
        g.record_frame(10.0)


def test_motion_spike_drops_fps_within_three_frames() -> None:
    g = FPSGovernor(initial_fps=60, min_fps_floor=30)
    _feed_static(g, 60)
    assert g.target_fps == 60
    for _ in range(2):
        g.signal_motion(40.0)
        g.record_frame(5.0)
    assert g.target_fps <= 45
    assert g.motion_envelope > 0.0


def test_motion_recovery_within_fifteen_frames() -> None:
    g = FPSGovernor(initial_fps=60, min_fps_floor=30)
    g.signal_motion(50.0)
    g.record_frame(5.0)
    dropped = g.target_fps
    assert dropped < 60
    for _ in range(20):
        g.signal_motion(0.0)
        g.record_frame(5.0)
    assert g.target_fps >= dropped
    assert g.target_fps >= 30


def test_p95_latency_still_steps_down_under_load() -> None:
    g = FPSGovernor(initial_fps=60, min_fps_floor=30)
    for _ in range(80):
        g.signal_motion(0.0)
        g.record_frame(20.0)
    assert g.target_fps <= 45


def test_signal_motion_logged_in_metrics() -> None:
    g = FPSGovernor(initial_fps=60)
    g.signal_motion(12.5)
    metrics = g.get_metrics()
    assert metrics["last_motion_signal"] == 12.5
    assert metrics["motion_envelope"] > 0.0
