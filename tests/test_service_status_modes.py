"""
Tests for NanoleafSyncService status reporting and backend mode classification.

These tests use injected capture/driver overrides so they exercise the real
service code without hardware or Qt.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np
import pytest

from nanoleaf_sync.capture.interfaces import CaptureBackend
from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.service import (
    _DEFAULT_CAPTURE_HEIGHT,
    _DEFAULT_CAPTURE_WIDTH,
    NanoleafSyncService,
)

RGB = tuple[int, int, int]


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
    reported_zone_count: int = 48
    zone_count: int = 48

    def initialize(self) -> None:
        self.initialized = True

    def send_frame(self, colors: Sequence[RGB]) -> None:
        self.frames_sent += 1

    def send_frame_with_timing(self, colors: Sequence[RGB]):
        self.frames_sent += 1
        return {"device_write_ms": 1.0, "live_send_policy": "response_required"}

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
        zone_count = 48
        cfg = AppConfig(
            fps=30,
            verbose=False,
            use_mock_capture=False,
            device_zone_count=zone_count,
            calibration=CalibrationConfig(
                device_zone_count=zone_count,
                corner_anchor_top_left=0,
                corner_anchor_top_right=zone_count // 4,
                corner_anchor_bottom_right=zone_count // 2,
                corner_anchor_bottom_left=(3 * zone_count) // 4,
            ),
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

    monkeypatch.setattr(
        "nanoleaf_sync.service.create_capture_backend", _fake_create_capture_backend
    )
    service._install_drivers()
    assert seen_cached_values == ["kwin-dbus"]


def test_status_includes_hdr_colour_path_diagnostics() -> None:
    cfg = AppConfig(
        fps=30,
        display_preset="hdr",
        compositor_hdr_mode=True,
        sdr_boost_nits=203.0,
        hdr_transfer="pq",
        hdr_primaries="bt2020",
        hdr_max_nits=1200.0,
    )
    capture = FakeCapture(name="kwin-dbus")
    capture.last_hdr_diagnostics = {
        "input_transfer": "pq",
        "input_primaries": "bt2020",
        "metadata_source": "unknown",
        "tone_mapping_applied": False,
        "assumption": "No backend metadata available; using user preset assumptions.",
        "hdr_max_nits": 1200.0,
    }
    svc = NanoleafSyncService(
        config=cfg, capture_backend_override=capture, driver_override=FakeDriver()
    )
    status = svc.get_status()
    hdr = status["hdr_colour_path"]
    assert hdr["display_preset"] == "hdr"
    assert hdr["effective_sdr_boost_scalar"] > 1.0
    assert hdr["capture_metadata_source"] == "unknown"
    assert hdr["display_referred"] is True
    assert any("kwin" in note.lower() for note in hdr["notes"])


def test_status_includes_portal_hdr_colour_path_diagnostics() -> None:
    cfg = AppConfig(
        fps=30,
        display_preset="hdr",
        compositor_hdr_mode=True,
        sdr_boost_nits=203.0,
    )
    capture = FakeCapture(name="xdg-portal")
    capture._last_frame_diag = {
        "format": "RGB",
        "stride": 7680,
        "caps": "video/x-raw,format=RGB,width=2560,height=1440",
    }
    svc = NanoleafSyncService(
        config=cfg, capture_backend_override=capture, driver_override=FakeDriver()
    )
    status = svc.get_status()
    hdr = status["hdr_colour_path"]
    assert hdr["backend"] == "xdg-portal"
    assert hdr["transfer"] == "srgb"
    assert hdr["primaries"] == "bt709"
    assert hdr["display_referred"] is True
    assert hdr["skip_display_gamut_adaptation"] is True
    assert hdr["sdr_boost_compensation_enabled"] is False
    assert hdr["portal_negotiated_format"] == "RGB"
    assert hdr["portal_stride"] == 7680
    assert hdr["portal_caps"] == "video/x-raw,format=RGB,width=2560,height=1440"
    assert hdr["source"] == "xdg-portal display-referred"
    assert any("portal" in note.lower() for note in hdr["notes"])


def test_one_shot_diagnostic_capture_populates_zone_rows_without_starting_runtime() -> None:
    cfg = AppConfig(fps=30, use_mock_capture=False, device_zone_count=12, display_preset="hdr")
    capture = FakeCapture(name="kwin-dbus", width=640, height=360)
    svc = NanoleafSyncService(
        config=cfg, capture_backend_override=capture, driver_override=FakeDriver()
    )
    result = svc.capture_one_diagnostic_frame()
    assert result["ok"] is True, result.get("message")
    status = svc.get_status()
    assert status["running"] is False
    assert len(status["_latest_zone_diagnostics"]) > 0
    assert int(status["captured_frame_width"]) == 640
    assert int(status["captured_frame_height"]) == 360


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

    monkeypatch.setattr(
        "nanoleaf_sync.service.create_capture_backend", _fake_create_capture_backend
    )
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

    monkeypatch.setattr(
        "nanoleaf_sync.service.create_capture_backend", _fake_create_capture_backend
    )
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

    monkeypatch.setattr(
        "nanoleaf_sync.service.create_capture_backend", _fake_create_capture_backend
    )
    NanoleafSyncService._reset_process_boot_probe_state()

    service_one._install_drivers()
    # Simulate a caller copying first-instance winner to the shared config object
    # before bringing up a second service in the same process.
    service_two.config = replace(
        service_two.config, auto_selected_backend=service_one.config.auto_selected_backend
    )
    service_two._install_drivers()

    assert seen_cached_values == [None, "kwin-dbus"]
    assert service_two.config.auto_selected_backend == "kwin-dbus"


def test_service_each_boot_policy_probes_once_per_process_under_concurrent_starts(
    monkeypatch,
) -> None:
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

    def _fake_build_auto_probe_signature(
        _width: int, _height: int, *, capture_monitor: str = ""
    ) -> str:
        start_barrier.wait(timeout=2.0)
        return "stable-sig"

    def _fake_create_capture_backend(**kwargs):
        with seen_lock:
            seen_cached_values.append(kwargs.get("cached_probe_winner"))
        return _FakeCaptureBackend()

    monkeypatch.setattr(
        "nanoleaf_sync.service._build_auto_probe_signature", _fake_build_auto_probe_signature
    )
    monkeypatch.setattr(
        "nanoleaf_sync.service.create_capture_backend", _fake_create_capture_backend
    )
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

    monkeypatch.setattr(
        "nanoleaf_sync.service.create_capture_backend", _fake_create_capture_backend
    )
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

    monkeypatch.setattr(
        "nanoleaf_sync.service.create_capture_backend", _fake_create_capture_backend
    )
    monkeypatch.setattr("nanoleaf_sync.service.ConfigManager", _FakeConfigManager)
    monkeypatch.setattr(
        "nanoleaf_sync.service._build_auto_probe_signature",
        lambda _w, _h, *, capture_monitor="": "sig-a",
    )
    monkeypatch.setattr(service, "make_device_driver", lambda **kwargs: FakeDriver())

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

    monkeypatch.setattr(
        "nanoleaf_sync.service.create_capture_backend", _fake_create_capture_backend
    )
    monkeypatch.setattr(
        "nanoleaf_sync.service._build_auto_probe_signature",
        lambda _w, _h, *, capture_monitor="": "stable-sig",
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

    monkeypatch.setattr(
        "nanoleaf_sync.service.create_capture_backend", _fake_create_capture_backend
    )
    monkeypatch.setattr(
        "nanoleaf_sync.service._build_auto_probe_signature",
        lambda _w, _h, *, capture_monitor="": "new-sig",
    )

    service._install_drivers()

    assert seen_cached_values == [None]


def test_service_reprobes_stale_kmsgrab_cache_even_when_signature_matches(monkeypatch) -> None:
    cfg = AppConfig(
        use_mock_capture=False,
        prefer_backend="auto",
        auto_probe_policy="on-change",
        auto_selected_backend="kmsgrab",
        auto_probe_signature="stable-sig",
    )
    service = NanoleafSyncService(config=cfg, driver_override=FakeDriver())
    seen_cached_values: list[str | None] = []

    class _FakeCaptureBackend:
        name = "kwin-dbus"
        last_capture_path = None

        def close(self) -> None:
            pass

    def _fake_create_capture_backend(**kwargs):
        seen_cached_values.append(kwargs.get("cached_probe_winner"))
        return _FakeCaptureBackend()

    monkeypatch.setattr(
        "nanoleaf_sync.service.create_capture_backend", _fake_create_capture_backend
    )
    monkeypatch.setattr(
        "nanoleaf_sync.service._build_auto_probe_signature",
        lambda _w, _h, *, capture_monitor="": "stable-sig",
    )

    service._install_drivers()

    assert seen_cached_values == [None]
    assert service._selection_reason == "fresh-probe"
    assert service.config.auto_selected_backend == "kwin-dbus"
