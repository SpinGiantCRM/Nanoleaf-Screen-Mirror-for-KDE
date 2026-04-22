from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import time
from typing import Callable, TypeVar


T = TypeVar("T")


def monotonic_s() -> float:
    return time.monotonic()


def call_with_timeout(func: Callable[[], T], timeout_s: float, *, op_name: str) -> T:
    if timeout_s <= 0.0:
        raise TimeoutError(f"{op_name} timeout must be > 0 seconds")

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="capture-probe")
    future = pool.submit(func)
    timed_out = False
    try:
        return future.result(timeout=timeout_s)
    except FutureTimeoutError as exc:
        timed_out = True
        future.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
        raise TimeoutError(f"{op_name} timed out after {timeout_s:.2f}s") from exc
    finally:
        if not timed_out:
            pool.shutdown(wait=True)
