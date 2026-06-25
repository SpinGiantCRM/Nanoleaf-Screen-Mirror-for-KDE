"""Shared persistent asyncio event-loop helper for capture backends."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Coroutine
from typing import TypeVar

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


class BackgroundAsyncLoop:
    """Run coroutines on a dedicated background asyncio loop thread."""

    def __init__(self, *, thread_name: str, wake_interval_s: float = 0.25) -> None:
        self._thread_name = str(thread_name)
        self._wake_interval_s = float(wake_interval_s)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._loop_ready = threading.Event()
        self._loop_lock = threading.Lock()
        self._loop_start_error: BaseException | None = None

    def run(self, coro: Coroutine[object, object, _T], *, timeout: float = 2.0) -> _T:
        loop = self.ensure_running()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout=max(0.1, float(timeout)))
        except TimeoutError:
            future.cancel()
            raise TimeoutError(
                f"{self._thread_name} async call timed out after {timeout:.1f}s"
            ) from None

    def ensure_running(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is not None and loop.is_running():
            return loop

        with self._loop_lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop

            self._loop_ready.clear()
            self._loop_thread = threading.Thread(
                target=self._loop_worker,
                name=self._thread_name,
                daemon=True,
            )
            self._loop_thread.start()

        self._loop_ready.wait(timeout=2.0)

        with self._loop_lock:
            if self._loop is None or not self._loop.is_running():
                if self._loop_start_error is not None:
                    raise RuntimeError(
                        f"Failed to initialize {self._thread_name} event loop."
                    ) from self._loop_start_error
                raise RuntimeError(f"Failed to initialize {self._thread_name} event loop.")
            return self._loop

    def shutdown(self, *, join_timeout_s: float = 3.0) -> None:
        with self._loop_lock:
            loop = self._loop
            thread = self._loop_thread

        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)

        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, float(join_timeout_s)))
            if thread.is_alive():
                logger.warning(
                    "%s thread did not exit within %.1fs",
                    self._thread_name,
                    join_timeout_s,
                )

        with self._loop_lock:
            self._loop = None
            self._loop_thread = None
            self._loop_ready.clear()

    def _loop_worker(self) -> None:
        try:
            loop = asyncio.new_event_loop()
            self._loop = loop
            self._loop_start_error = None
            asyncio.set_event_loop(loop)

            def _keep_loop_waking() -> None:
                if loop.is_running():
                    loop.call_later(self._wake_interval_s, _keep_loop_waking)

            loop.call_soon(self._loop_ready.set)
            loop.call_soon(_keep_loop_waking)
            loop.run_forever()
            loop.close()
        except Exception as exc:
            self._loop_start_error = exc
            self._loop = None
            self._loop_ready.set()
