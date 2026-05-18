from __future__ import annotations

import threading
import time

from nanoleaf_sync.runtime.startup import reinitialize_backends, run_runtime_engine
from nanoleaf_sync.runtime.state import RuntimeState
from nanoleaf_sync.runtime.zone_derivation import effective_zone_count
from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.runtime.startup import RuntimeLifecycle


class _Closable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_reinitialize_backends_exposes_none_between_close_and_reinstall() -> None:
    state = RuntimeState()
    capture_holder = {"value": _Closable()}
    driver_holder = {"value": _Closable()}

    close_done = threading.Event()
    install_started = threading.Event()
    allow_install_finish = threading.Event()

    def get_capture():
        return capture_holder["value"]

    def get_driver():
        return driver_holder["value"]

    def close_backends() -> None:
        capture = capture_holder["value"]
        if capture is not None:
            capture.close()
        capture_holder["value"] = None

        driver = driver_holder["value"]
        if driver is not None:
            driver.close()
        driver_holder["value"] = None
        close_done.set()

    def install_drivers() -> None:
        install_started.set()
        allow_install_finish.wait(timeout=1.0)
        capture_holder["value"] = _Closable()
        driver_holder["value"] = _Closable()

    thread = threading.Thread(
        target=reinitialize_backends,
        kwargs={
            "install_drivers": install_drivers,
            "close_backends": close_backends,
            "state": state,
        },
    )
    thread.start()

    assert close_done.wait(timeout=1.0)
    assert install_started.wait(timeout=1.0)
    assert get_capture() is None
    assert get_driver() is None

    allow_install_finish.set()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert get_capture() is not None
    assert get_driver() is not None


def test_zone_derivation_ignores_detected_strip_length_when_config_is_legacy_auto() -> None:
    cfg = AppConfig(
        zones=[ZoneConfig(x=0.0, y=0.0, w=1.0, h=0.5), ZoneConfig(x=0.0, y=0.5, w=1.0, h=0.5)],
        device_zone_count=0,
    )
    assert effective_zone_count(config=cfg, detected_device_zone_count=64) == 2


def test_runtime_lifecycle_start_is_single_flight_under_rapid_requests() -> None:
    state = RuntimeState()
    started = threading.Event()
    release = threading.Event()
    run_count = {"value": 0}

    def _runner() -> None:
        run_count["value"] += 1
        started.set()
        state.mark_startup(True)
        release.wait(timeout=2.0)

    lifecycle = RuntimeLifecycle(state=state, runner=_runner)

    def _start() -> None:
        lifecycle.start(startup_timeout_s=0.01)

    workers = [threading.Thread(target=_start) for _ in range(10)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=1.0)

    assert started.wait(timeout=1.0)
    assert run_count["value"] == 1
    release.set()
    lifecycle.join(timeout=1.0)


def test_runtime_lifecycle_stop_from_starting_state_cleans_up_to_idle() -> None:
    state = RuntimeState()
    allow_exit = threading.Event()

    def _runner() -> None:
        # Deliberately keep startup pending until stop() is issued.
        while not state.stop_event.is_set():
            time.sleep(0.001)
        allow_exit.wait(timeout=0.2)

    lifecycle = RuntimeLifecycle(state=state, runner=_runner)
    assert lifecycle.start(startup_timeout_s=0.01) is True
    assert lifecycle.startup_state() == "starting"
    lifecycle.stop()
    allow_exit.set()
    lifecycle.join(timeout=1.0)
    assert lifecycle.startup_state() == "idle"


def test_run_runtime_engine_shutdowns_backends_when_run_loop_raises(monkeypatch) -> None:
    state = RuntimeState()
    calls: list[str] = []

    def _install_drivers() -> None:
        calls.append("install")

    def _run_loop(**_kwargs) -> None:
        calls.append("run_loop")
        raise RuntimeError("synthetic loop failure")

    def _close_backends() -> None:
        calls.append("close")

    def _clear_backends() -> None:
        calls.append("clear")

    monkeypatch.setattr("nanoleaf_sync.runtime.engine.run_loop", _run_loop)

    try:
        run_runtime_engine(
            config=AppConfig(),
            state=state,
            get_capture=lambda: object(),
            get_driver=lambda: object(),
            install_drivers=_install_drivers,
            close_backends=_close_backends,
            clear_backends=_clear_backends,
        )
    except RuntimeError as exc:
        assert str(exc) == "synthetic loop failure"
    else:
        raise AssertionError("run_runtime_engine should re-raise unexpected run_loop failures")

    assert calls == ["install", "run_loop", "close", "clear"]
