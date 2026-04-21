from __future__ import annotations

import threading

from nanoleaf_sync.runtime.startup import reinitialize_backends
from nanoleaf_sync.runtime.state import RuntimeState


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
