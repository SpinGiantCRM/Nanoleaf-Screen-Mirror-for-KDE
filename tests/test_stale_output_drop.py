from __future__ import annotations

import time

from nanoleaf_sync.runtime.engine_frame import (
    compute_max_send_age_ms,
    evaluate_stale_output_drop,
)


def test_compute_max_send_age_ms_respects_min_and_fps_budget() -> None:
    at_60 = compute_max_send_age_ms(target_fps=60.0, min_max_send_age_ms=60.0)
    assert at_60 == 60.0

    at_120 = compute_max_send_age_ms(target_fps=120.0, min_max_send_age_ms=60.0)
    assert at_120 == 60.0

    at_10 = compute_max_send_age_ms(
        target_fps=10.0, min_max_send_age_ms=60.0, budget_multiplier=2.0
    )
    assert at_10 == 200.0


def test_evaluate_stale_output_drop_disabled() -> None:
    now = time.perf_counter()
    should_drop, age_ms, max_age_ms, reason = evaluate_stale_output_drop(
        captured_at=now - 1.0,
        now=now,
        target_fps=60.0,
        stale_frame_drop_enabled=False,
        min_max_send_age_ms=60.0,
        max_send_age_frame_budget_multiplier=2.0,
    )
    assert should_drop is False
    assert age_ms > 900.0
    assert max_age_ms == 60.0
    assert reason == ""


def test_evaluate_stale_output_drop_when_frame_is_fresh() -> None:
    now = time.perf_counter()
    should_drop, age_ms, max_age_ms, reason = evaluate_stale_output_drop(
        captured_at=now - 0.01,
        now=now,
        target_fps=60.0,
        stale_frame_drop_enabled=True,
        min_max_send_age_ms=60.0,
        max_send_age_frame_budget_multiplier=2.0,
    )
    assert should_drop is False
    assert 0.0 <= age_ms < 60.0
    assert max_age_ms == 60.0
    assert reason == ""


def test_evaluate_stale_output_drop_when_frame_is_stale() -> None:
    now = time.perf_counter()
    should_drop, age_ms, max_age_ms, reason = evaluate_stale_output_drop(
        captured_at=now - 0.5,
        now=now,
        target_fps=60.0,
        stale_frame_drop_enabled=True,
        min_max_send_age_ms=60.0,
        max_send_age_frame_budget_multiplier=2.0,
    )
    assert should_drop is True
    assert age_ms > max_age_ms
    assert "frame_age_ms=" in reason
