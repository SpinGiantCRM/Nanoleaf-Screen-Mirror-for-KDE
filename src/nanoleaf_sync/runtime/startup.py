from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from threading import Thread

from nanoleaf_sync.color.capture_metadata import invalidate_plasma_hdr_cache
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.errors import translate_runtime_error
from nanoleaf_sync.runtime.state import RuntimeState

logger = logging.getLogger(__name__)

_PRIORITY_TARGET_BY_MODE = {
    "normal": None,
    "high": -5,
    "very_high_experimental": -10,
}


def _current_nice_value(who: int = 0) -> int | None:
    try:
        return int(os.getpriority(os.PRIO_PROCESS, int(who)))
    except Exception:
        logger.debug("Unable to read process nice value", exc_info=True)
        return None


def _normalized_priority_mode(config: AppConfig) -> str:
    mode = str(getattr(config, "performance_priority", "normal") or "normal").strip().lower()
    return mode if mode in _PRIORITY_TARGET_BY_MODE else "normal"


def _desired_nice_value(target: int, *, who: int = 0) -> int:
    current_nice = _current_nice_value(who)
    return int(target) if current_nice is None else min(int(current_nice), int(target))


def apply_process_priority(*, config: AppConfig, state: RuntimeState) -> None:
    mode = _normalized_priority_mode(config)
    target = _PRIORITY_TARGET_BY_MODE.get(mode)
    state.configured_priority_mode = mode
    state.effective_nice_value = _current_nice_value()
    state.priority_apply_error = ""

    if target is None:
        state.priority_apply_status = "not_requested"
        return

    desired_nice = _desired_nice_value(int(target))
    try:
        os.setpriority(os.PRIO_PROCESS, 0, int(desired_nice))
        state.priority_apply_status = "applied"
        state.effective_nice_value = _current_nice_value()
    except Exception as exc:
        state.priority_apply_status = "failed"
        state.priority_apply_error = str(exc)
        state.effective_nice_value = _current_nice_value()


def apply_current_thread_priority(
    *, config: AppConfig, state: RuntimeState, thread_label: str
) -> None:
    mode = _normalized_priority_mode(config)
    target = _PRIORITY_TARGET_BY_MODE.get(mode)
    if target is None or state.priority_apply_status == "failed":
        return

    native_id = getattr(threading, "get_native_id", lambda: 0)()
    who = int(native_id or 0)
    desired_nice = _desired_nice_value(int(target), who=who)
    try:
        os.setpriority(os.PRIO_PROCESS, who, int(desired_nice))
        state.effective_nice_value = _current_nice_value()
        if state.priority_apply_status not in {"applied", "partial_failed"}:
            state.priority_apply_status = "applied"
    except Exception as exc:
        state.priority_apply_status = "partial_failed"
        state.priority_apply_error = f"{thread_label}: {exc}"
        state.effective_nice_value = _current_nice_value()


def reset_startup(state: RuntimeState) -> None:
    state.stop_event.clear()
    state.startup_complete.clear()
    state.startup_succeeded = False
    state.last_error = None
    state.last_error_kind = None
    state.last_error_guidance = None
    state.lifecycle_state = "starting"
    state.start_failure_reason = ""


def wait_for_startup(state: RuntimeState, timeout_s: float = 1.0) -> bool:
    state.startup_complete.wait(timeout=timeout_s)
    return not (state.startup_complete.is_set() and not state.startup_succeeded)


def initialize_or_fail(
    *,
    install_drivers: Callable[[], object],
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
        state.start_failure_reason = translated.summary
        state.lifecycle_state = "failed"
        state.mark_startup(False)
        logger.exception("service startup failed")
        close_backends()
        return False

    state.capture_backend_ready = True
    state.driver_ready = True
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
    install_drivers: Callable[[], object],
    close_backends: Callable[[], None],
    state: RuntimeState,
) -> None:
    state.is_reinitializing = True
    state.reinit_pause.set()
    invalidate_plasma_hdr_cache()
    state.clear_smoothing_history()
    state.smoothing_dimension_signature = None
    state.wait_for_worker_idle(timeout_s=0.5)
    try:
        close_backends()
        now_ts = time.perf_counter()
        install_drivers()
        state.last_reinit_ts = now_ts
        with state._lock:
            state.consecutive_errors = 0
    except Exception:
        logger.exception("backend reinitialization failed")
    finally:
        state.is_reinitializing = False
        state.reinit_pause.clear()


def shutdown_backends(
    *,
    close_backends: Callable[[], None],
    clear_backends: Callable[[], None],
    send_final_frame: Callable[[], None] | None = None,
) -> None:
    if send_final_frame is not None:
        try:
            send_final_frame()
        except Exception:
            logger.debug("send_final_frame failed during shutdown", exc_info=True)

    # Run close_backends in a short-lived thread with timeout to prevent
    # indefinite blocking when the HID device or capture backend is unresponsive.
    close_thread = threading.Thread(target=close_backends, name="shutdown-close", daemon=True)
    close_thread.start()
    close_thread.join(timeout=5.0)
    if close_thread.is_alive():
        logger.warning(
            "close_backends did not complete within shutdown timeout (5s); "
            "it may still be blocked in device IO"
        )

    clear_backends()


def run_runtime_engine(
    *,
    config: AppConfig,
    state: RuntimeState,
    get_capture: Callable[[], object],
    get_driver: Callable[[], object],
    install_drivers: Callable[[], object],
    close_backends: Callable[[], None],
    clear_backends: Callable[[], None],
    send_final_frame: Callable[[], None] | None = None,
    can_mirroring_write: Callable[[], bool] | None = None,
) -> None:
    try:
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
            use_legacy_pipeline=bool(getattr(config, "use_legacy_pipeline", False)),
            can_mirroring_write=can_mirroring_write,
        )
    except Exception as e:
        translated = translate_runtime_error(e)
        state.last_error = translated.summary
        state.last_error_kind = translated.kind
        state.last_error_guidance = translated.guidance
        state.start_failure_reason = translated.summary
        state.lifecycle_state = "failed"
        state.mark_startup(False)
        state.stop_event.set()
        logger.exception("runtime engine crashed")
    finally:
        shutdown_backends(
            close_backends=close_backends,
            clear_backends=clear_backends,
            send_final_frame=send_final_frame,
        )


class RuntimeLifecycle:
    def __init__(
        self,
        *,
        state: RuntimeState,
        runner: Callable[[], None],
    ) -> None:
        self._state = state
        self._runner = runner
        self._thread: Thread | None = None
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
            self._state.lifecycle_state = "starting"
            self._thread.start()

        startup_completed = self._state.startup_complete.wait(
            timeout=max(0.0, float(startup_timeout_s))
        )
        if not startup_completed:
            # Startup is still in-flight (for example, awaiting user portal consent).
            with self._lock:
                self._state.lifecycle_state = "starting"
                self._sync_state_locked()
            return True
        if not self._state.startup_succeeded:
            self.join(timeout=0.2)
            with self._lock:
                self._state.lifecycle_state = "failed"
                self._sync_state_locked()
            return False
        with self._lock:
            self._sync_state_locked()
        return self.is_running()

    def stop(self, *, join_timeout: float | None = None) -> bool:
        with self._lock:
            self._sync_state_locked()
            if self._state_name in {"starting", "running"}:
                self._state_name = "stopping"
                self._state.lifecycle_state = "stopping"
            elif self._state_name in {"idle", "error"}:
                return True
        self._state.stop_event.set()
        if join_timeout is not None:
            self.join(timeout=join_timeout)
            with self._lock:
                self._sync_state_locked()
                if self._thread is not None and self._thread.is_alive():
                    self._state_name = "error"
                    self._state.lifecycle_state = "failed"
                    self._state.last_error = (
                        self._state.last_error or "Service did not stop within timeout"
                    )
                    self._state.last_error_kind = self._state.last_error_kind or "stop-timeout"
                    self._state.last_error_guidance = (
                        self._state.last_error_guidance
                        or "The runtime thread is stuck. Check USB device connection and retry."
                    )
            return not self.is_running()
        return True

    def join(self, timeout: float | None = None) -> None:
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
                self._state_name = (
                    "running" if self._state.startup_complete.is_set() else "starting"
                )
                self._state.lifecycle_state = self._state_name
            elif (
                self._state_name == "starting"
                and self._state.startup_complete.is_set()
                and self._state.startup_succeeded
            ):
                self._state_name = "running"
                self._state.lifecycle_state = "running"
            return
        # Thread is not alive.
        if self._state_name == "stopping":
            self._state_name = "idle"
            self._state.lifecycle_state = "idle"
            return
        if self._state_name == "error":
            # Preserve explicitly set error state (e.g. from a stuck stop).
            self._state.lifecycle_state = "failed"
            return
        if self._state.startup_complete.is_set() and not self._state.startup_succeeded:
            self._state_name = "error"
            self._state.lifecycle_state = "failed"
        else:
            self._state_name = "idle"
            self._state.lifecycle_state = "idle"
