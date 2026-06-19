from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from nanoleaf_sync.capture.interfaces import CaptureBackend
from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.service import NanoleafSyncService

RGB = tuple[int, int, int]


def _wait_until(
    predicate,
    *,
    timeout_s: float = 1.0,
    step_s: float = 0.01,
) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step_s)
    return predicate()


def _valid_runtime_cfg(**kwargs) -> AppConfig:
    zone_count = int(kwargs.pop("device_zone_count", 48))
    return AppConfig(
        device_zone_count=zone_count,
        calibration=CalibrationConfig(
            device_zone_count=zone_count,
            corner_anchor_top_left=0,
            corner_anchor_top_right=zone_count // 4,
            corner_anchor_bottom_right=zone_count // 2,
            corner_anchor_bottom_left=(3 * zone_count) // 4,
        ),
        **kwargs,
    )


class FailingOnceCapture(CaptureBackend):
    name = "failing-once"
    last_capture_path: str | None = None

    def __init__(self, width: int, height: int) -> None:
        self._frame = np.zeros((height, width, 3), dtype=np.uint8)
        self._failed = False

    def capture(self) -> np.ndarray:
        if not self._failed:
            self._failed = True
            raise RuntimeError("synthetic capture failure")
        return self._frame


@dataclass
class FakeDriver:
    last_colors: Sequence[RGB] | None = None
    frames_sent: int = 0
    initialized: bool = False
    initialize_calls: int = 0
    close_calls: int = 0
    sent_frames: list[list[RGB]] | None = None

    name: str = "fake-usb"
    zone_count: int = 0

    def initialize(self) -> None:
        self.initialize_calls += 1
        self.initialized = True

    def send_frame(self, colors: Sequence[RGB]) -> None:
        frame = list(colors)
        self.last_colors = frame
        if self.sent_frames is None:
            self.sent_frames = []
        self.sent_frames.append(frame)
        self.frames_sent += 1

    def close(self) -> None:
        self.close_calls += 1
        self.initialized = False


def test_service_recovers_from_single_frame_exception() -> None:
    cfg = _valid_runtime_cfg(
        fps=30,
        verbose=False,
        # Use real pipeline code paths but via injected capture/driver.
        use_mock_capture=False,
    )

    capture = FailingOnceCapture(width=16, height=9)
    driver = FakeDriver()

    service = NanoleafSyncService(
        config=cfg,
        capture_backend_override=capture,
        driver_override=driver,
    )

    assert service.start() is True
    assert _wait_until(lambda: driver.frames_sent >= 1, timeout_s=1.0)
    service.stop()
    service.join(timeout=2.0)
    assert _wait_until(lambda: not service.is_running(), timeout_s=1.0)

    assert driver.initialized is False
    assert driver.frames_sent >= 1
    assert service.last_error is None

    status = service.get_status()
    assert status["frames_sent"] >= 1
    assert status["max_consecutive_errors"] >= 1


def test_service_can_restart_after_stop() -> None:
    cfg = _valid_runtime_cfg(
        fps=30,
        verbose=False,
        use_mock_capture=False,
    )
    capture = FailingOnceCapture(width=16, height=9)
    driver = FakeDriver()
    service = NanoleafSyncService(
        config=cfg,
        capture_backend_override=capture,
        driver_override=driver,
    )

    assert service.start() is True
    assert _wait_until(lambda: driver.frames_sent >= 1, timeout_s=1.0)
    service.stop()
    service.join(timeout=2.0)
    assert _wait_until(lambda: not service.is_running(), timeout_s=1.0)
    first_run_frames = driver.frames_sent
    assert first_run_frames >= 1

    # Start again and verify state/loop can produce fresh frames.
    assert service.start() is True
    assert _wait_until(lambda: driver.frames_sent > first_run_frames, timeout_s=1.0)
    service.stop()
    service.join(timeout=2.0)
    assert _wait_until(lambda: not service.is_running(), timeout_s=1.0)

    status = service.get_status()
    assert status["frames_sent"] >= 1
    assert driver.frames_sent > first_run_frames


class BlockingCapture(CaptureBackend):
    name = "blocking"
    last_capture_path: str | None = None

    def __init__(self, width: int, height: int, *, close_unblocks: bool) -> None:
        self._frame = np.zeros((height, width, 3), dtype=np.uint8)
        self._close_unblocks = bool(close_unblocks)
        self._entered = threading.Event()
        self._released = threading.Event()
        self.close_calls = 0
        self.close_thread_ids: list[int] = []

    def capture(self) -> np.ndarray:
        self._entered.set()
        self._released.wait()
        return self._frame

    def close(self) -> None:
        self.close_calls += 1
        self.close_thread_ids.append(threading.get_ident())
        if self._close_unblocks:
            self._released.set()

    def wait_until_blocked(self, timeout: float = 1.0) -> bool:
        return self._entered.wait(timeout=timeout)

    def release(self) -> None:
        self._released.set()


def test_stop_does_not_close_shared_backends_from_caller_thread() -> None:
    cfg = _valid_runtime_cfg(fps=30, verbose=False, use_mock_capture=False, device_zone_count=8)
    capture = BlockingCapture(width=16, height=9, close_unblocks=True)
    driver = FakeDriver()
    caller_thread_id = threading.get_ident()
    service = NanoleafSyncService(
        config=cfg, capture_backend_override=capture, driver_override=driver
    )

    assert service.start() is True
    assert capture.wait_until_blocked(timeout=1.0) is True

    # Stop detaches the stuck thread and returns True so the UI can recover.
    assert service.stop(timeout=0.05) is True
    assert service.is_running() is False
    # close is never called from the caller thread.
    assert capture.close_calls == 0
    assert driver.close_calls == 0

    # Release the captured thread; the detached runtime will finish on its own.
    capture.release()
    assert _wait_until(lambda: capture.close_calls >= 1, timeout_s=2.0)
    assert _wait_until(lambda: not service.is_running(), timeout_s=1.0)
    assert capture.close_calls >= 1
    assert caller_thread_id not in capture.close_thread_ids
    assert driver.initialized is False
    assert service.stop(timeout=0.2) is True


def test_stop_detaches_stuck_runtime_and_reports_not_running() -> None:
    cfg = AppConfig(fps=30, verbose=False, use_mock_capture=False)
    capture = BlockingCapture(width=16, height=9, close_unblocks=False)
    driver = FakeDriver()
    service = NanoleafSyncService(
        config=cfg, capture_backend_override=capture, driver_override=driver
    )

    assert service.start() is True
    assert capture.wait_until_blocked(timeout=1.0) is True

    # Stop detaches the stuck thread so the UI can recover.
    assert service.stop(timeout=0.05) is True
    assert service.is_running() is False

    capture.release()
    assert service.stop(timeout=1.0) is True
    assert _wait_until(lambda: not service.is_running(), timeout_s=1.0)


class FailingInitDriver(FakeDriver):
    def initialize(self) -> None:
        self.initialize_calls += 1
        raise RuntimeError("synthetic init failure")


class ClosableCapture(CaptureBackend):
    name = "closable"
    last_capture_path: str | None = None

    def __init__(self) -> None:
        self.close_calls = 0

    def capture(self) -> np.ndarray:
        return np.zeros((9, 16, 3), dtype=np.uint8)

    def close(self) -> None:
        self.close_calls += 1


def test_stop_does_not_initialize_unopened_hid() -> None:
    driver = FakeDriver()
    service = NanoleafSyncService(
        config=_valid_runtime_cfg(use_mock_capture=False), driver_override=driver
    )

    assert service.stop(timeout=0.01) is True

    assert driver.initialize_calls == 0
    assert driver.frames_sent == 0
    assert driver.close_calls == 0


def test_stop_after_partial_startup_is_safe_and_does_not_send_black_frame() -> None:
    capture = ClosableCapture()
    driver = FailingInitDriver()
    service = NanoleafSyncService(
        config=_valid_runtime_cfg(use_mock_capture=False),
        capture_backend_override=capture,
        driver_override=driver,
    )

    assert service.start() is False
    assert service.stop(timeout=0.1) is True

    assert driver.initialize_calls == 1
    assert driver.frames_sent == 0
    assert driver.close_calls == 1
    assert capture.close_calls == 1
    assert service._driver is None


def test_stop_black_frame_requires_ready_existing_driver() -> None:
    service = NanoleafSyncService(
        config=_valid_runtime_cfg(device_zone_count=4, use_mock_capture=False)
    )

    service._send_stop_black_frame()

    driver = FakeDriver(zone_count=4)
    service._driver = driver
    service._runtime.driver_ready = False
    service._send_stop_black_frame()
    assert driver.frames_sent == 0

    service._runtime.driver_ready = True
    service._send_stop_black_frame()

    assert driver.frames_sent == 1
    assert driver.last_colors == [(0, 0, 0)] * 4


def test_runtime_shutdown_sends_final_black_only_after_driver_ready() -> None:
    cfg = _valid_runtime_cfg(fps=30, verbose=False, use_mock_capture=False, device_zone_count=4)
    capture = FailingOnceCapture(width=16, height=9)
    driver = FakeDriver(zone_count=4)
    service = NanoleafSyncService(
        config=cfg, capture_backend_override=capture, driver_override=driver
    )

    assert service.start() is True
    assert _wait_until(lambda: driver.frames_sent >= 1, timeout_s=1.0)
    assert service.stop(timeout=1.0) is True

    assert driver.sent_frames is not None
    assert driver.sent_frames[-1] == [(0, 0, 0)] * 4
    assert service._driver is None
