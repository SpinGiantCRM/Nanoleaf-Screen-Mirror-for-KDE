from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

import numpy as np

from capture.interfaces import CaptureBackend
from config.model import AppConfig
from service import NanoleafSyncService


RGB = Tuple[int, int, int]


@dataclass
class FakeCapture(CaptureBackend):
    name: str = "mock"
    last_capture_path: str | None = None
    width: int = 16
    height: int = 9

    def __post_init__(self):
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
        use_mock_device=True,
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
