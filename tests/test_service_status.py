from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

import numpy as np
import pytest

from nanoleaf_sync.capture.interfaces import CaptureBackend
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.service import NanoleafSyncService


RGB = Tuple[int, int, int]


@dataclass
class FakeCapture(CaptureBackend):
    name: str = "mock"
    last_capture_path: str | None = None
    width: int = 16
    height: int = 9

    def __post_init__(self) -> None:
        self._frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

    def capture(self) -> np.ndarray:
        return self._frame

    def close(self) -> None:
        pass


@dataclass
class FakeDriver:
    frames_sent: int = 0
    initialized: bool = False
    closed: bool = False

    def initialize(self) -> None:
        self.initialized = True

    def send_frame(self, colors: Sequence[RGB]) -> None:
        self.frames_sent += 1

    def close(self) -> None:
        self.closed = True


class FailingInitDriver(FakeDriver):
    def initialize(self) -> None:
        raise RuntimeError("synthetic initialize failure")


def _make_cfg() -> AppConfig:
    return AppConfig(
        fps=30,
        verbose=False,
        use_mock_capture=False,
    )


def test_service_startup_failure_sets_error_and_not_running() -> None:
    svc = NanoleafSyncService(
        config=_make_cfg(),
        capture_backend_override=FakeCapture(name="mock"),
        driver_override=FailingInitDriver(),
    )

    started = svc.start()

    assert started is False
    assert svc.is_running() is False
    status = svc.get_status()
    assert status["running"] is False
    assert "synthetic initialize failure" in (status["last_error"] or "")


def test_capture_mode_replay_is_explicit() -> None:
    svc = NanoleafSyncService(
        config=_make_cfg(),
        capture_backend_override=FakeCapture(name="replay"),
        driver_override=FakeDriver(),
    )

    assert svc.start() is True
    status = svc.get_status()
    svc.stop()
    svc.join(timeout=2.0)

    assert status["capture_mode"] == "replay"


def test_make_device_driver_uses_real_driver() -> None:
    svc = NanoleafSyncService(config=_make_cfg())
    driver = svc._make_device_driver()
    assert driver.__class__.__name__ == "NanoleafUSBDriver"


def test_status_exposes_device_mode_and_error_guidance() -> None:
    svc = NanoleafSyncService(
        config=_make_cfg(),
        capture_backend_override=FakeCapture(name="mock"),
        driver_override=FailingInitDriver(),
    )

    svc.start()
    status = svc.get_status()
    assert status["device_mode"] == "real-usb"
    assert status["last_error_kind"] is not None
    assert status["last_error_guidance"] is not None


def test_make_device_driver_requires_non_zero_vid_pid_for_real_device() -> None:
    cfg = AppConfig(device_vid=0, device_pid=0)
    svc = NanoleafSyncService(config=cfg)
    with pytest.raises(ValueError) as excinfo:
        svc._make_device_driver()
    assert "non-zero device_vid/device_pid" in str(excinfo.value)
