from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Sequence, Tuple

import numpy as np

from capture.interfaces import CaptureBackend
from config.model import AppConfig
from service import NanoleafSyncService


RGB = Tuple[int, int, int]


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

    name: str = "fake-usb"

    def initialize(self) -> None:
        self.initialized = True

    def send_frame(self, colors: Sequence[RGB]) -> None:
        self.last_colors = list(colors)
        self.frames_sent += 1

    def close(self) -> None:
        self.initialized = False


def test_service_recovers_from_single_frame_exception() -> None:
    cfg = AppConfig(
        fps=30,
        verbose=False,
        # Use real pipeline code paths but via injected capture/driver.
        use_mock_capture=False,
        use_mock_device=True,
    )

    capture = FailingOnceCapture(width=16, height=9)
    driver = FakeDriver()

    service = NanoleafSyncService(
        config=cfg,
        capture_backend_override=capture,
        driver_override=driver,
    )

    service.start()
    time.sleep(0.25)
    service.stop()
    service.join(timeout=2.0)

    assert driver.initialized is False
    assert driver.frames_sent >= 1
    assert service.last_error is None

    status = service.get_status()
    assert status["frames_sent"] >= 1
    assert status["max_consecutive_errors"] >= 1
