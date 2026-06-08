"""Tests for RuntimeState thread-safety helpers."""

from __future__ import annotations

import pytest

from nanoleaf_sync.runtime.state import RuntimeState


def test_runtime_state_has_lock() -> None:
    state = RuntimeState()
    assert hasattr(state, "_lock")
    assert state._lock.acquire(blocking=False)
    state._lock.release()


def test_assert_locked_requires_lock_held() -> None:
    state = RuntimeState()
    with pytest.raises(RuntimeError, match="requires _lock"):
        state._assert_locked()


def test_assert_locked_passes_when_lock_held() -> None:
    state = RuntimeState()
    with state._lock:
        state._assert_locked()


def test_reset_for_start_under_lock() -> None:
    state = RuntimeState()
    state.frames_sent = 42
    with state._lock:
        state.reset_for_start()
    assert state.frames_sent == 0
