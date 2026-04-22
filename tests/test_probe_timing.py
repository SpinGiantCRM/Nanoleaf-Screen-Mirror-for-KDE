from __future__ import annotations

import threading
import time

import pytest

from nanoleaf_sync.capture.probe_timing import call_with_timeout


def test_call_with_timeout_returns_promptly_when_worker_blocks() -> None:
    release = threading.Event()

    def _never_finishes() -> None:
        release.wait(timeout=5.0)

    start = time.monotonic()
    with pytest.raises(TimeoutError, match="probe timed out"):
        call_with_timeout(_never_finishes, timeout_s=0.05, op_name="probe")
    elapsed = time.monotonic() - start
    release.set()

    assert elapsed < 0.5
