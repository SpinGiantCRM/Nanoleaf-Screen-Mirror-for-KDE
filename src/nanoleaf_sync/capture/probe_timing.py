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

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="capture-probe") as pool:
        future = pool.submit(func)
        try:
            return future.result(timeout=timeout_s)
        except FutureTimeoutError as exc:
            raise TimeoutError(f"{op_name} timed out after {timeout_s:.2f}s") from exc
