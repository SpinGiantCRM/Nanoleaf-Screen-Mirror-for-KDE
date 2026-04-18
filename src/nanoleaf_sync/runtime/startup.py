from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.errors import translate_runtime_error
from nanoleaf_sync.runtime.state import RuntimeState


logger = logging.getLogger(__name__)


def reset_startup(state: RuntimeState) -> None:
    state.stop_event.clear()
    state.startup_complete.clear()
    state.startup_succeeded = False


def wait_for_startup(state: RuntimeState, timeout_s: float = 1.0) -> bool:
    state.startup_complete.wait(timeout=timeout_s)
    return not (state.startup_complete.is_set() and not state.startup_succeeded)


def initialize_or_fail(
    *,
    install_drivers: Callable[[], None],
    close_backends: Callable[[], None],
    state: RuntimeState,
) -> bool:
    try:
        install_drivers()
    except Exception as e:
        translated = translate_runtime_error(e)
        state.last_error = translated.summary
        state.last_error_kind = translated.kind
        state.last_error_guidance = translated.guidance
        state.mark_startup(False)
        logger.exception("service startup failed")
        close_backends()
        return False

    state.mark_startup(True)
    return True


def should_reinitialize(
    *,
    state: RuntimeState,
    error_limit: int,
    backoff_s: float,
    now_ts: float,
) -> bool:
    if state.consecutive_errors < max(1, error_limit):
        return False
    return (now_ts - state.last_reinit_ts) >= max(0.0, backoff_s)


def reinitialize_backends(
    *,
    install_drivers: Callable[[], None],
    close_backends: Callable[[], None],
    state: RuntimeState,
) -> None:
    state.is_reinitializing = True
    close_backends()
    now_ts = time.perf_counter()
    try:
        install_drivers()
        state.last_reinit_ts = now_ts
    except Exception:
        logger.exception("backend reinitialization failed")
    finally:
        state.consecutive_errors = 0
        state.is_reinitializing = False


def shutdown_backends(
    *,
    close_backends: Callable[[], None],
    clear_backends: Callable[[], None],
) -> None:
    close_backends()
    clear_backends()


def run_runtime_engine(
    *,
    config: AppConfig,
    state: RuntimeState,
    get_capture: Callable[[], object],
    get_driver: Callable[[], object],
    install_drivers: Callable[[], None],
    close_backends: Callable[[], None],
    clear_backends: Callable[[], None],
) -> None:
    from nanoleaf_sync.runtime.engine import run_loop

    state.reset_for_start()
    if not initialize_or_fail(
        install_drivers=install_drivers,
        close_backends=close_backends,
        state=state,
    ):
        clear_backends()
        return

    run_loop(
        config=config,
        state=state,
        get_capture=get_capture,
        get_driver=get_driver,
        install_drivers=install_drivers,
        close_backends=close_backends,
    )
    shutdown_backends(
        close_backends=close_backends,
        clear_backends=clear_backends,
    )


class RuntimeLifecycle:
    def __init__(self, *, state: RuntimeState, runner: Callable[[], None]) -> None:
        self._state = state
        self._runner = runner
        self._thread: Optional[threading.Thread] = None

    def start(self, *, startup_timeout_s: float = 1.0) -> bool:
        if self.is_running():
            return True

        reset_startup(self._state)
        self._thread = threading.Thread(
            target=self._runner,
            name="nanoleaf-sync",
            daemon=True,
        )
        self._thread.start()
        if not wait_for_startup(self._state, timeout_s=startup_timeout_s):
            self.join(timeout=0.2)
            return False
        return self.is_running()

    def stop(self) -> None:
        self._state.stop_event.set()

    def join(self, timeout: Optional[float] = None) -> None:
        if self._thread is None:
            return
        self._thread.join(timeout=timeout)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
