"""
Tests for NanoleafSyncService status reporting and backend mode classification.

These tests use injected capture/driver overrides so they exercise the real
service code without hardware or Qt.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from dataclasses import replace
from typing import Sequence, Tuple

import numpy as np
import pytest

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


@dataclass
class FailingCloseDriver(FakeDriver):
    def close(self) -> None:
        self.closed = True
        raise RuntimeError("driver close failed")


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


def test_close_backends_clears_references_on_close_failures() -> None:
    class _FailingCloseCapture(FakeCapture):
        def close(self) -> None:
            raise RuntimeError("capture close failed")

    service = NanoleafSyncService(
        config=AppConfig(fps=30, verbose=False, use_mock_capture=False),
        capture_backend_override=_FailingCloseCapture(name="kwin-dbus"),
        driver_override=FailingCloseDriver(),
    )
    service._install_drivers()

    service._close_backends()

    assert service._capture is None
    assert service._driver is None


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
    NanoleafSyncService._reset_process_boot_probe_state()
    service._install_drivers()
    service._close_backends()
    service._install_drivers()
    assert seen_cached_values == [None, "kwin-dbus"]


def test_service_each_boot_policy_across_multiple_instances(monkeypatch) -> None:
    cfg = AppConfig(use_mock_capture=False, prefer_backend="auto", auto_probe_policy="each-boot")
    service_one = NanoleafSyncService(config=cfg, driver_override=FakeDriver())
    service_two = NanoleafSyncService(config=cfg, driver_override=FakeDriver())
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
    NanoleafSyncService._reset_process_boot_probe_state()

    service_one._install_drivers()
    service_two._install_drivers()

    assert seen_cached_values == [None, ""]
    assert service_one.config.auto_selected_backend == "kwin-dbus"
    assert service_two.config.auto_selected_backend == "kwin-dbus"


def test_service_each_boot_policy_second_instance_uses_in_memory_winner_cache(monkeypatch) -> None:
    cfg = AppConfig(use_mock_capture=False, prefer_backend="auto", auto_probe_policy="each-boot")
    service_one = NanoleafSyncService(config=cfg, driver_override=FakeDriver())
    service_two = NanoleafSyncService(config=cfg, driver_override=FakeDriver())
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
    NanoleafSyncService._reset_process_boot_probe_state()

    service_one._install_drivers()
    # Simulate a caller copying first-instance winner to the shared config object
    # before bringing up a second service in the same process.
    service_two.config = replace(service_two.config, auto_selected_backend=service_one.config.auto_selected_backend)
    service_two._install_drivers()

    assert seen_cached_values == [None, "kwin-dbus"]
    assert service_two.config.auto_selected_backend == "kwin-dbus"


def test_service_each_boot_policy_probes_once_per_process_under_concurrent_starts(monkeypatch) -> None:
    cfg = AppConfig(use_mock_capture=False, prefer_backend="auto", auto_probe_policy="each-boot")
    service_one = NanoleafSyncService(config=cfg, driver_override=FakeDriver())
    service_two = NanoleafSyncService(config=cfg, driver_override=FakeDriver())
    seen_cached_values: list[str | None] = []
    seen_lock = threading.Lock()
    start_barrier = threading.Barrier(2)

    class _FakeCaptureBackend:
        name = "kwin-dbus"
        last_capture_path = None

        def close(self) -> None:
            pass

    def _fake_build_auto_probe_signature(_width: int, _height: int) -> str:
        start_barrier.wait(timeout=2.0)
        return "stable-sig"

    def _fake_create_capture_backend(**kwargs):
        with seen_lock:
            seen_cached_values.append(kwargs.get("cached_probe_winner"))
        return _FakeCaptureBackend()

    monkeypatch.setattr("nanoleaf_sync.service._build_auto_probe_signature", _fake_build_auto_probe_signature)
    monkeypatch.setattr("nanoleaf_sync.service.create_capture_backend", _fake_create_capture_backend)
    NanoleafSyncService._reset_process_boot_probe_state()

    first = threading.Thread(target=service_one._install_drivers)
    second = threading.Thread(target=service_two._install_drivers)
    first.start()
    second.start()
    first.join(timeout=2.0)
    second.join(timeout=2.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert sorted(seen_cached_values, key=lambda value: value is not None) == [None, ""]
    assert service_one.config.auto_selected_backend == "kwin-dbus"
    assert service_two.config.auto_selected_backend == "kwin-dbus"


def test_service_each_boot_policy_allows_retry_after_failed_install(monkeypatch) -> None:
    cfg = AppConfig(use_mock_capture=False, prefer_backend="auto", auto_probe_policy="each-boot")
    service = NanoleafSyncService(config=cfg, driver_override=FakeDriver())
    seen_cached_values: list[str | None] = []
    attempt = 0

    class _FakeCaptureBackend:
        name = "kwin-dbus"
        last_capture_path = None

        def close(self) -> None:
            pass

    def _fake_create_capture_backend(**kwargs):
        nonlocal attempt
        attempt += 1
        seen_cached_values.append(kwargs.get("cached_probe_winner"))
        if attempt == 1:
            raise RuntimeError("probe failed")
        return _FakeCaptureBackend()

    monkeypatch.setattr("nanoleaf_sync.service.create_capture_backend", _fake_create_capture_backend)
    NanoleafSyncService._reset_process_boot_probe_state()

    with pytest.raises(RuntimeError, match="probe failed"):
        service._install_drivers()

    service._install_drivers()

    assert seen_cached_values == [None, None]


def test_service_first_run_policy_creates_cache_and_persists_metadata(monkeypatch) -> None:
    cfg = AppConfig(use_mock_capture=False, prefer_backend="auto", auto_probe_policy="first-run")
    service = NanoleafSyncService(config=cfg)
    seen_cached_values: list[str | None] = []
    saved_configs: list[AppConfig] = []

    class _FakeCaptureBackend:
        name = "kwin-dbus"
        last_capture_path = None

        def close(self) -> None:
            pass

    class _FakeConfigManager:
        def save(self, saved_cfg: AppConfig) -> None:
            saved_configs.append(saved_cfg)

    def _fake_create_capture_backend(**kwargs):
        seen_cached_values.append(kwargs.get("cached_probe_winner"))
        return _FakeCaptureBackend()

    monkeypatch.setattr("nanoleaf_sync.service.create_capture_backend", _fake_create_capture_backend)
    monkeypatch.setattr("nanoleaf_sync.service.ConfigManager", _FakeConfigManager)
    monkeypatch.setattr("nanoleaf_sync.service._build_auto_probe_signature", lambda _w, _h: "sig-a")
    monkeypatch.setattr(service, "_make_device_driver", lambda: FakeDriver())

    service._install_drivers()

    assert seen_cached_values == [None]
    assert service.config.auto_selected_backend == "kwin-dbus"
    assert service.config.auto_probe_signature == "sig-a"
    assert service.config.auto_probe_timestamp
    assert cfg.auto_selected_backend == ""
    assert len(saved_configs) == 1


def test_service_on_change_policy_reuses_cache_when_signature_matches(monkeypatch) -> None:
    cfg = AppConfig(
        use_mock_capture=False,
        prefer_backend="auto",
        auto_probe_policy="on-change",
        auto_selected_backend="kwin-dbus",
        auto_probe_signature="stable-sig",
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
    monkeypatch.setattr(
        "nanoleaf_sync.service._build_auto_probe_signature",
        lambda _w, _h: "stable-sig",
    )

    service._install_drivers()

    assert seen_cached_values == ["kwin-dbus"]


def test_service_on_change_policy_reprobes_when_signature_changes(monkeypatch) -> None:
    cfg = AppConfig(
        use_mock_capture=False,
        prefer_backend="auto",
        auto_probe_policy="on-change",
        auto_selected_backend="kwin-dbus",
        auto_probe_signature="old-sig",
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
    monkeypatch.setattr("nanoleaf_sync.service._build_auto_probe_signature", lambda _w, _h: "new-sig")

    service._install_drivers()

    assert seen_cached_values == [None]
