"""
Tests for NanoleafSyncService status reporting and backend mode classification.

These tests use injected capture/driver overrides so they exercise the real
service code without hardware or Qt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence, Tuple

import numpy as np

from nanoleaf_sync.capture.interfaces import CaptureBackend
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.service import NanoleafSyncService, _DEFAULT_CAPTURE_HEIGHT, _DEFAULT_CAPTURE_WIDTH


RGB = Tuple[int, int, int]


@dataclass
class FakeCapture(CaptureBackend):
    name: str = "mock"
    last_capture_path: str | None = None
    width: int = 16
    height: int = 9
    _frame: np.ndarray = None

    def __post_init__(self):
        self._frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

    def capture(self) -> np.ndarray:
        return self._frame

    def close(self) -> None:
        pass


@dataclass
class FakeDriver:
    frames_sent: int = 0
    closed: bool = False
    initialized: bool = False

    def initialize(self) -> None:
        self.initialized = True

    def send_frame(self, colors: Sequence[RGB]) -> None:
        self.frames_sent += 1

    def close(self) -> None:
        self.closed = True


class TestServiceStatusAndMode:
    def _make_service(
        self, capture_name="mock"
    ) -> tuple[NanoleafSyncService, FakeCapture, FakeDriver]:
        cfg = AppConfig(
            fps=30, verbose=False, use_mock_capture=False
        )
        capture = FakeCapture(name=capture_name)
        driver = FakeDriver()
        svc = NanoleafSyncService(
            config=cfg,
            capture_backend_override=capture,
            driver_override=driver,
        )
        return svc, capture, driver

    def test_initial_status_not_running(self):
        svc, _, _ = self._make_service()
        status = svc.get_status()
        assert status["running"] is False
        assert status["last_error"] is None

    def test_capture_mode_mock(self):
        svc, capture, driver = self._make_service(capture_name="mock")
        svc.start()
        time.sleep(0.1)
        status = svc.get_status()
        svc.stop()
        svc.join(timeout=2.0)
        assert status["capture_mode"] == "mock"

    def test_capture_mode_stub_fallback(self):
        svc, capture, driver = self._make_service(capture_name="kwin-dbus")
        svc.start()
        time.sleep(0.1)
        status = svc.get_status()
        svc.stop()
        svc.join(timeout=2.0)
        assert status["capture_mode"] == "kwin-dbus"

    def test_capture_dimensions_stored(self):
        """Service stores and reports capture dimensions for diagnostics."""
        svc, _, _ = self._make_service()
        assert svc._capture_width == _DEFAULT_CAPTURE_WIDTH
        assert svc._capture_height == _DEFAULT_CAPTURE_HEIGHT
        status = svc.get_status()
        assert status["capture_width"] == _DEFAULT_CAPTURE_WIDTH
        assert status["capture_height"] == _DEFAULT_CAPTURE_HEIGHT

    def test_status_running_while_active(self):
        svc, _, _ = self._make_service()
        svc.start()
        time.sleep(0.1)
        assert svc.get_status()["running"] is True
        svc.stop()
        svc.join(timeout=2.0)
        assert svc.get_status()["running"] is False

    def test_driver_closed_after_stop(self):
        cfg = AppConfig(fps=30, use_mock_capture=False)
        capture = FakeCapture(name="mock")
        driver = FakeDriver()
        svc = NanoleafSyncService(
            config=cfg,
            capture_backend_override=capture,
            driver_override=driver,
        )
        svc.start()
        time.sleep(0.1)
        svc.stop()
        svc.join(timeout=2.0)
        # Driver must be closed when the service shuts down.
        assert driver.closed is True

    def test_frames_sent_after_run(self):
        svc, _, driver = self._make_service()
        svc.start()
        time.sleep(0.15)
        svc.stop()
        svc.join(timeout=2.0)
        assert driver.frames_sent >= 1


def test_service_passes_cached_probe_winner_on_reinitialize(monkeypatch) -> None:
    cfg = AppConfig(fps=30, verbose=False, use_mock_capture=False, prefer_backend="auto")
    driver = FakeDriver()
    service = NanoleafSyncService(config=cfg, driver_override=driver)
    seen_cached_values: list[str | None] = []

    class _FakeCaptureBackend:
        def __init__(self, name: str) -> None:
            self.name = name
            self.last_capture_path = None

        def close(self) -> None:
            pass

    def _fake_create_capture_backend(**kwargs):
        seen_cached_values.append(kwargs.get("cached_probe_winner"))
        return _FakeCaptureBackend("kwin-dbus")

    monkeypatch.setattr(
        "nanoleaf_sync.service.create_capture_backend",
        _fake_create_capture_backend,
    )

    service._install_drivers()
    service._close_backends()
    service._install_drivers()

    assert seen_cached_values == [None, "kwin-dbus"]


def test_service_first_run_policy_skips_probe_when_cached_winner_exists(monkeypatch) -> None:
    cfg = AppConfig(
        use_mock_capture=False,
        prefer_backend="auto",
        auto_probe_policy="first-run",
        auto_selected_backend="kwin-dbus",
    )
    driver = FakeDriver()
    service = NanoleafSyncService(config=cfg, driver_override=driver)
    seen_cached_values: list[str | None] = []

    class _FakeCaptureBackend:
        name = "kwin-dbus"
        last_capture_path = None

        def close(self) -> None:
            pass

    def _fake_create_capture_backend(**kwargs):
        seen_cached_values.append(kwargs.get("cached_probe_winner"))
        return _FakeCaptureBackend()

    monkeypatch.setattr("nanoleaf_sync.service.create_capture_backend", _fake_create_capture_backend)
    service._install_drivers()
    assert seen_cached_values == ["kwin-dbus"]


def test_service_each_boot_policy_probes_once_per_process(monkeypatch) -> None:
    cfg = AppConfig(use_mock_capture=False, prefer_backend="auto", auto_probe_policy="each-boot")
    driver = FakeDriver()
    service = NanoleafSyncService(config=cfg, driver_override=driver)
    seen_cached_values: list[str | None] = []

    class _FakeCaptureBackend:
        name = "kwin-dbus"
        last_capture_path = None

        def close(self) -> None:
            pass

    def _fake_create_capture_backend(**kwargs):
        seen_cached_values.append(kwargs.get("cached_probe_winner"))
        return _FakeCaptureBackend()

    monkeypatch.setattr("nanoleaf_sync.service.create_capture_backend", _fake_create_capture_backend)
    monkeypatch.setattr("nanoleaf_sync.service._PROCESS_BOOT_PROBE_DONE", False)
    service._install_drivers()
    service._close_backends()
    service._install_drivers()
    assert seen_cached_values == [None, "kwin-dbus"]
