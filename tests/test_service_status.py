from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

import numpy as np
import pytest

from nanoleaf_sync.capture.interfaces import CaptureBackend
from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
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
    zone_count = 48
    return AppConfig(
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


def test_service_status_retains_configured_strip_zone_count_without_auto_mode() -> None:
    svc = NanoleafSyncService(config=AppConfig(device_zone_count=24))
    assert svc.config.device_zone_count == 24


def test_service_status_reports_detected_configured_and_effective_zone_counts() -> None:
    cfg = AppConfig(device_zone_count=24)
    cfg.calibration.device_zone_count = 24
    svc = NanoleafSyncService(config=cfg)
    svc._device_zone_count = 48
    status = svc.get_status()
    assert status["detected_device_zone_count"] == 48
    assert status["configured_device_zone_count"] == 24
    assert status["effective_runtime_zone_count"] == 24
    assert status["calibration_device_zone_count"] == 24


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
    assert status["lifecycle_state"] == "failed"
    assert "synthetic initialize failure" in status["start_failure_reason"]
    assert status["capture_backend_ready"] is True
    assert status["driver_ready"] is False
    assert status["first_frame_seen"] is False
    assert status["first_frame_sent"] is False


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
    driver = svc.make_device_driver()
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
    assert status["requested_capture_backend"] == svc.config.prefer_backend
    assert status["effective_capture_backend"] in {"mock", None}
    assert status["selection_reason"] == "explicit"
    assert status["selected_capture_backend"] in {"mock", ""}


def test_make_device_driver_requires_non_zero_vid_pid_for_real_device() -> None:
    cfg = AppConfig(device_vid=0, device_pid=0)
    svc = NanoleafSyncService(config=cfg)
    with pytest.raises(ValueError) as excinfo:
        svc.make_device_driver()
    assert "non-zero device_vid/device_pid" in str(excinfo.value)


def test_status_exposes_requested_vs_effective_backend_for_auto_cached_probe(monkeypatch) -> None:
    cfg = AppConfig(
        fps=30,
        verbose=False,
        use_mock_capture=False,
        prefer_backend="auto",
        auto_selected_backend="kwin-dbus",
        auto_probe_policy="first-run",
    )
    svc = NanoleafSyncService(config=cfg, driver_override=FakeDriver())

    class _FakeCaptureBackend:
        name = "kwin-dbus"
        last_capture_path = None

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        "nanoleaf_sync.service.create_capture_backend", lambda **_kwargs: _FakeCaptureBackend()
    )
    svc._install_drivers()

    status = svc.get_status()
    assert status["requested_capture_backend"] == "auto"
    assert status["effective_capture_backend"] == "kwin-dbus"
    assert status["selection_reason"] == "cached-probe"
    assert status["auto_probe_policy"] == "first-run"
    assert status["cached_probe_backend"] == "kwin-dbus"
    assert status["selected_capture_backend"] == "kwin-dbus"
    assert status["backend_unresolved_reason"] == ""
    assert "policy=first-run" in status["backend_selection_details"]


def test_clear_backends_resets_cached_device_metadata() -> None:
    svc = NanoleafSyncService(config=AppConfig())
    svc._device_discovered = True
    svc._device_model = "Nanoleaf USB Lightstrip"
    svc._device_zone_count = 32

    svc._clear_backends()
    status = svc.get_status()

    assert status["device_discovered"] is False
    assert status["device_model"] is None
    assert status["device_zone_count"] is None
    assert status["detected_device_zone_count"] is None
    assert status["effective_runtime_zone_count"] is None


def test_one_shot_diagnostic_capture_does_not_pollute_live_latency_metrics() -> None:
    svc = NanoleafSyncService(
        config=_make_cfg(),
        capture_backend_override=FakeCapture(name="mock"),
        driver_override=FakeDriver(),
    )
    result = svc.capture_one_diagnostic_frame()
    assert result["ok"] is True
    status = svc.get_status()
    assert status["latency_measurement"] is None
