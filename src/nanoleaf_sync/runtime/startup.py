from __future__ import annotations

import logging
import os
import time
import threading
from threading import Thread
from typing import Callable, Optional

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.errors import translate_runtime_error
from nanoleaf_sync.runtime.state import RuntimeState


logger = logging.getLogger(__name__)


def _current_nice_value() -> int | None:
    try:
        return int(os.getpriority(os.PRIO_PROCESS, 0))
    except Exception:
        return None


def apply_process_priority(*, config: AppConfig, state: RuntimeState) -> None:
    mode = str(getattr(config, "performance_priority", "normal") or "normal").strip().lower()
    target_by_mode = {
        "normal": None,
        "high": -5,
        "very_high_experimental": -10,
    }
    target = target_by_mode.get(mode)
    state.configured_priority_mode = mode if mode in target_by_mode else "normal"
    state.effective_nice_value = _current_nice_value()
    state.priority_apply_error = ""

    if target is None:
        state.priority_apply_status = "not_requested"
        return

    current_nice = _current_nice_value()
    desired_nice = target if current_nice is None else min(int(current_nice), int(target))
    try:
        os.setpriority(os.PRIO_PROCESS, 0, int(desired_nice))
        state.priority_apply_status = "applied"
        state.effective_nice_value = _current_nice_value()
    except Exception as exc:
        state.priority_apply_status = "failed"
        state.priority_apply_error = str(exc)
        state.effective_nice_value = _current_nice_value()


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
    try:
        close_backends()
        now_ts = time.perf_counter()
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
    apply_process_priority(config=config, state=state)
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
    def __init__(
        self,
        *,
        state: RuntimeState,
        runner: Callable[[], None],
        on_stop_requested: Callable[[], None] | None = None,
    ) -> None:
        self._state = state
        self._runner = runner
        self._on_stop_requested = on_stop_requested
        self._thread: Optional[Thread] = None
        self._lock = threading.Lock()
        self._state_name = "idle"

    def start(self, *, startup_timeout_s: float = 1.0) -> bool:
        with self._lock:
            self._sync_state_locked()
            if self._state_name in {"starting", "running"}:
                return True
            if self._state_name == "stopping":
                return False

            reset_startup(self._state)
            self._thread = Thread(
                target=self._runner,
                name="nanoleaf-sync",
                daemon=True,
            )
            self._state_name = "starting"
            self._thread.start()

        startup_completed = self._state.startup_complete.wait(timeout=max(0.0, float(startup_timeout_s)))
        if not startup_completed:
            # Startup is still in-flight (for example, awaiting user portal consent).
            with self._lock:
                self._sync_state_locked()
            return True
        if not self._state.startup_succeeded:
            self.join(timeout=0.2)
            with self._lock:
                self._sync_state_locked()
            return False
        with self._lock:
            self._sync_state_locked()
        return self.is_running()

    def stop(self, *, join_timeout: Optional[float] = None) -> bool:
        stop_requested = False
        with self._lock:
            self._sync_state_locked()
            if self._state_name in {"starting", "running"}:
                self._state_name = "stopping"
                stop_requested = True
            elif self._state_name in {"idle", "error"}:
                return True
        self._state.stop_event.set()
        if stop_requested and self._on_stop_requested is not None:
            try:
                self._on_stop_requested()
            except Exception:
                logger.exception("runtime stop callback failed")
        if join_timeout is not None:
            self.join(timeout=join_timeout)
            return not self.is_running()
        return True

    def join(self, timeout: Optional[float] = None) -> None:
        if self._thread is None:
            return
        self._thread.join(timeout=timeout)
        with self._lock:
            self._sync_state_locked()
            if self._thread is not None and not self._thread.is_alive():
                self._thread = None

    def is_running(self) -> bool:
        with self._lock:
            self._sync_state_locked()
            return bool(self._thread is not None and self._thread.is_alive())

    def startup_state(self) -> str:
        with self._lock:
            self._sync_state_locked()
            return self._state_name

    def _sync_state_locked(self) -> None:
        thread_alive = self._thread is not None and self._thread.is_alive()
        if thread_alive:
            if self._state_name in {"idle", "error"}:
                self._state_name = "running" if self._state.startup_complete.is_set() else "starting"
            elif self._state_name == "starting" and self._state.startup_complete.is_set() and self._state.startup_succeeded:
                self._state_name = "running"
            return
        if self._state_name == "stopping":
            self._state_name = "idle"
            return
        if self._state.startup_complete.is_set() and not self._state.startup_succeeded:
            self._state_name = "error"
        else:
            self._state_name = "idle"
