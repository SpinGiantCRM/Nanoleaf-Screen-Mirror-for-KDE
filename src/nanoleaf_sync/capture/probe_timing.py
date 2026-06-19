from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar, cast

T = TypeVar("T")


def monotonic_s() -> float:
    return time.monotonic()


@dataclass
class _CallResult:
    value: T | None = None
    error: BaseException | None = None


def call_with_timeout(func: Callable[[], T], timeout_s: float, *, op_name: str) -> T:
    """Run ``func`` with a timeout using a dedicated daemon thread.

    Timeout behavior is cooperative only from the caller side: on timeout this
    function raises ``TimeoutError`` promptly, but Python cannot forcibly
    interrupt a blocking call running in another thread (for example a
    non-interruptible HID read). In those cases the worker thread may continue
    running until the call returns; it is marked daemon so it will not block
    interpreter shutdown.
    """

    if timeout_s <= 0.0:
        raise TimeoutError(f"{op_name} timeout must be > 0 seconds")

    finished = threading.Event()
    result: _CallResult = _CallResult()

    def _run() -> None:
        try:
            result.value = func()
        except BaseException as exc:  # noqa: BLE001 - surface caller exception
            result.error = exc
        finally:
            finished.set()

    worker = threading.Thread(target=_run, name="capture-probe-call", daemon=True)
    worker.start()

    if not finished.wait(timeout_s):
        raise TimeoutError(f"{op_name} timed out after {timeout_s:.2f}s")

    if result.error is not None:
        raise result.error

    return cast(T, result.value)
