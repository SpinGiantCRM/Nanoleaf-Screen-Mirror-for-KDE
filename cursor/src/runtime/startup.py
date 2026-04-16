from __future__ import annotations

import logging
import time
from typing import Callable

from runtime.state import RuntimeState


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
        state.last_error = str(e)
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
    close_backends()
    now_ts = time.perf_counter()
    try:
        install_drivers()
        state.last_reinit_ts = now_ts
    except Exception:
        logger.exception("backend reinitialization failed")
    finally:
        state.consecutive_errors = 0


def shutdown_backends(
    *,
    close_backends: Callable[[], None],
    clear_backends: Callable[[], None],
) -> None:
    close_backends()
    clear_backends()
