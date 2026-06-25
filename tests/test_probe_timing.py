from __future__ import annotations

import threading
import time

import pytest

import nanoleaf_sync.capture.probe_timing as probe_timing
from nanoleaf_sync.capture.probe_timing import call_with_timeout


def test_call_with_timeout_timeout_does_not_wait_for_blocked_call() -> None:
    release = threading.Event()

    def _never_finishes() -> None:
        release.wait(timeout=5.0)

    start = time.monotonic()
    with pytest.raises(TimeoutError, match="probe timed out"):
        call_with_timeout(_never_finishes, timeout_s=0.05, op_name="probe")
    elapsed = time.monotonic() - start
    release.set()

    assert elapsed < 0.5


def test_call_with_timeout_repeated_calls_do_not_use_thread_pool_executor() -> None:
    assert not hasattr(probe_timing, "ThreadPoolExecutor")
    for _ in range(10):
        assert call_with_timeout(lambda: 123, timeout_s=0.2, op_name="probe") == 123
