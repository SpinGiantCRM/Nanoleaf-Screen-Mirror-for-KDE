from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from nanoleaf_sync.capture.interfaces import CaptureBackend
from nanoleaf_sync.config.model import AppConfig, CalibrationConfig, ZoneConfig
from nanoleaf_sync.runtime.engine import run_loop
from nanoleaf_sync.runtime.output_session import OutputSessionController
from nanoleaf_sync.runtime.startup import RuntimeLifecycle
from nanoleaf_sync.runtime.state import RuntimeState
from nanoleaf_sync.service import NanoleafSyncService
from nanoleaf_sync.ui.tray_app import NanoleafTrayApp


def _wait_until(predicate, *, timeout_s: float = 1.0, step_s: float = 0.01) -> bool:
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


class _FastCapture(CaptureBackend):
    name = "kwin-dbus"
    last_capture_path = "kwin-dbus:test"

    def __init__(self, width: int = 32, height: int = 24) -> None:
        self._frame = np.zeros((height, width, 3), dtype=np.uint8)
        self._frame[:, :] = [40, 50, 60]

    def capture(self) -> np.ndarray:
        return self._frame


class _CountingDriver:
    reported_zone_count = 48
    zone_count = 48
    frames_sent = 0
    initialized = False
    initialize_calls = 0

    def initialize(self) -> None:
        self.initialize_calls += 1
        self.initialized = True

    def send_frame(self, _colors) -> None:
        self.frames_sent += 1

    def send_frame_with_timing(self, _colors):
        self.frames_sent += 1
        return {"device_write_ms": 0.1}

    def close(self) -> None:
        self.initialized = False


def test_runtime_lifecycle_rejects_start_while_stopping() -> None:
    state = RuntimeState()
    release = threading.Event()

    def _runner() -> None:
        state.mark_startup(True)
        release.wait(timeout=2.0)

    lifecycle = RuntimeLifecycle(state=state, runner=_runner)
    assert lifecycle.start(startup_timeout_s=0.05) is True
    lifecycle.stop(join_timeout=None)
    assert lifecycle.startup_state() == "stopping"
    assert lifecycle.start(startup_timeout_s=0.05) is False
    release.set()
    lifecycle.join(timeout=1.0)
    assert lifecycle.startup_state() == "idle"


def test_service_start_while_running_is_single_flight() -> None:
    cfg = _valid_runtime_cfg(fps=30, verbose=False, use_mock_capture=False)
    capture = _FastCapture()
    driver = _CountingDriver()
    service = NanoleafSyncService(
        config=cfg,
        capture_backend_override=capture,
        driver_override=driver,
    )

    assert service.start() is True
    assert service.start() is True
    assert _wait_until(lambda: driver.frames_sent >= 1, timeout_s=1.0)
    assert driver.initialize_calls == 1
    service.stop(timeout=2.0)
    service.join(timeout=2.0)
    assert _wait_until(lambda: not service.is_running(), timeout_s=1.0)


def test_stale_mirroring_generation_blocks_output_writes() -> None:
    session = OutputSessionController()
    generation = session.begin_mirroring_generation()
    runtime_state = RuntimeState()
    stop_after = {"done": False}

    def _stop_soon() -> None:
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline and runtime_state.frames_sent < 1:
            time.sleep(0.02)
        stop_after["done"] = True
        runtime_state.stop_event.set()

    threading.Thread(target=_stop_soon, daemon=True).start()
    run_loop(
        config=_valid_runtime_cfg(fps=60, min_max_send_age_ms=500.0),
        state=runtime_state,
        get_capture=lambda: _FastCapture(),
        get_driver=lambda: _CountingDriver(),
        install_drivers=lambda: True,
        close_backends=lambda: None,
        can_mirroring_write=lambda gen=generation: session.can_mirroring_write(gen),
    )
    assert runtime_state.frames_sent >= 1

    session.revoke_mirroring_generation(generation)
    stale_state = RuntimeState()
    threading.Thread(target=_stop_soon, daemon=True).start()
    run_loop(
        config=_valid_runtime_cfg(fps=60, min_max_send_age_ms=500.0),
        state=stale_state,
        get_capture=lambda: _FastCapture(),
        get_driver=lambda: _CountingDriver(),
        install_drivers=lambda: True,
        close_backends=lambda: None,
        can_mirroring_write=lambda gen=generation: session.can_mirroring_write(gen),
    )
    assert stale_state.output_owner_dropped_frames >= 1
    assert stale_state.first_frame_sent is False


def test_restart_rebinds_fresh_mirroring_generation() -> None:
    session = OutputSessionController()
    service = SimpleNamespace(mirroring_generation=0)

    def bind_mirroring_generation(generation: int) -> None:
        service.mirroring_generation = generation

    def set_output_session_guard(guard) -> None:
        service._output_session_guard = guard

    service.bind_mirroring_generation = bind_mirroring_generation
    service.set_output_session_guard = set_output_session_guard

    tray = SimpleNamespace(
        _output_session=session,
        _bind_output_session_guard=NanoleafTrayApp._bind_output_session_guard,
    )

    NanoleafTrayApp._bind_output_session_guard(tray, service)  # type: ignore[arg-type]
    first_generation = int(service.mirroring_generation)
    assert service._output_session_guard() is True

    session.revoke_mirroring_generation(first_generation)
    assert service._output_session_guard() is False

    NanoleafTrayApp._bind_output_session_guard(tray, service)  # type: ignore[arg-type]
    assert int(service.mirroring_generation) > first_generation
    assert service._output_session_guard() is True


class _FakeCfgMgr:
    def __init__(self, cfg: AppConfig) -> None:
        self.config = cfg
        self.saved: AppConfig | None = None

    def save(self, cfg: AppConfig) -> None:
        self.saved = cfg


class _FakeService:
    def __init__(self, *, config: AppConfig, running: bool = False) -> None:
        self.config = config
        self._running = running
        self.stop_calls = 0

    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> dict:
        return {"startup_state": "running" if self._running else "idle"}

    def start(self) -> bool:
        self._running = True
        return True

    def stop(self, timeout: float | None = None) -> bool:
        self.stop_calls += 1
        self._running = False
        return True

    def join(self, timeout: float | None = None) -> None:
        return None


class _FakeDialog:
    def __init__(self, parent, cfg, **_kwargs) -> None:
        self._cfg = cfg

    def exec(self) -> int:
        return 1

    def wants_display_configurator(self) -> bool:
        return False

    def settings_applied_in_session(self) -> bool:
        return False

    def updated_config(self) -> AppConfig:
        return AppConfig(
            zones=[
                ZoneConfig(x=0.0, y=0.0, w=0.5, h=1.0),
                ZoneConfig(x=0.5, y=0.0, w=0.5, h=1.0),
            ],
            device_zone_count=0,
            output_channel_order="grb",
        )


def test_settings_save_while_mirroring_replaces_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.SettingsDialog", _FakeDialog)
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app.NanoleafSyncService", _FakeService)

    original_cfg = AppConfig(
        zones=[ZoneConfig(x=0.0, y=0.0, w=1.0, h=1.0)],
        device_zone_count=1,
    )
    service = _FakeService(config=original_cfg, running=True)

    def _restart_service(*, was_running: bool) -> None:
        NanoleafTrayApp._restart_mirroring_service(
            fake_tray,
            was_running=was_running,
        )

    fake_tray = SimpleNamespace(
        config=original_cfg,
        cfg_mgr=_FakeCfgMgr(original_cfg),
        service=service,
        _calibration_dialog=None,
        QDialog=SimpleNamespace(DialogCode=SimpleNamespace(Accepted=1)),
        QSystemTrayIcon=SimpleNamespace(MessageIcon=SimpleNamespace(Warning=1)),
        tray_icon=SimpleNamespace(showMessage=lambda *_a, **_k: None),
        _refresh_mode_labels=lambda: None,
        _send_calibration_preview=lambda _colors: None,
        on_stop=lambda: None,
        on_start=lambda: None,
        _close_preview_driver=lambda: False,
        _preview_paused_service=False,
        _output_session=OutputSessionController(),
        _shutdown_timeout_s=1.0,
        _request_stop=lambda **kwargs: service.stop(),
        _sync_config_for_mirroring=lambda: None,
        _restart_mirroring_service=_restart_service,
    )

    NanoleafTrayApp.on_settings(fake_tray)  # type: ignore[arg-type]

    assert fake_tray.cfg_mgr.saved is not None
    assert fake_tray.cfg_mgr.saved.device_zone_count == 0
    assert fake_tray.cfg_mgr.saved.output_channel_order == "grb"
    assert fake_tray.service.config.device_zone_count == 0
    assert fake_tray.service.config.output_channel_order == "grb"
    assert service.stop_calls >= 1
